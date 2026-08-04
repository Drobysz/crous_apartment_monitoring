# ruff: noqa: B008
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.schemas import ReferralOwnerExchangeRequest, ReferralPayoutRequest
from app.core.config import Settings, get_settings
from app.db.models import ReferralPayout, ReferralProgram
from app.db.session import get_session
from app.referrals.service import (
    WithdrawalError,
    balances,
    consume_owner_login_token,
    request_payout,
)

router = APIRouter(prefix="/referral", tags=["referral-owner"])


def _owner_key(settings: Settings) -> bytes:
    if settings.admin_session_secret is None:
        raise HTTPException(status_code=503, detail={"code": "owner_sessions_unavailable"})
    return settings.admin_session_secret.get_secret_value().encode()


def _encode(program_id: int, settings: Settings) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(
            {"pid": program_id, "exp": int((datetime.now(UTC) + timedelta(hours=8)).timestamp())},
            separators=(",", ":"),
        ).encode()
    ).rstrip(b"=")
    signature = hmac.new(_owner_key(settings), body, hashlib.sha256).digest()
    return f"{body.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _decode(value: str, settings: Settings) -> int:
    try:
        body, signature = value.split(".")
        expected = hmac.new(_owner_key(settings), body.encode(), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if not hmac.compare_digest(expected, actual) or int(payload["exp"]) <= int(
            datetime.now(UTC).timestamp()
        ):
            raise ValueError
        return int(payload["pid"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "invalid_owner_session"}
        ) from error


async def owner_program(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ReferralProgram:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "owner_authentication_required"})
    program = await session.get(ReferralProgram, _decode(authorization[7:], settings))
    if program is None or program.deleted_at is not None or not program.is_active:
        raise HTTPException(status_code=401, detail={"code": "owner_session_unavailable"})
    return program


@router.post("/auth/exchange")
async def exchange(
    payload: ReferralOwnerExchangeRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    program = await consume_owner_login_token(session, payload.token)
    if program is None:
        await session.rollback()
        raise HTTPException(
            status_code=401, detail={"code": "invalid_or_expired_referral_login_token"}
        )
    await session.commit()
    return {
        "access_token": _encode(program.id, settings),
        "token_type": "bearer",
        "expires_in_seconds": 28800,
    }


@router.get("/dashboard")
async def dashboard(
    program: ReferralProgram = Depends(owner_program), session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    value = await balances(session, program.id)
    return {
        "id": program.id,
        "referral_code": program.referral_code,
        "available_cents": value.available_cents,
        "reserved_cents": value.reserved_cents,
        "paid_cents": value.paid_cents,
        "earned_cents": value.earned_cents,
        "currency": "EUR",
    }


@router.get("/stats")
async def stats(
    program: ReferralProgram = Depends(owner_program), session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    value = await balances(session, program.id)
    return {
        "pending_cents": value.pending_cents,
        "earned_cents": value.earned_cents,
        "available_cents": value.available_cents,
        "reserved_cents": value.reserved_cents,
        "paid_cents": value.paid_cents,
        "reversed_cents": value.reversed_cents,
        "currency": "EUR",
    }


@router.get("/payouts")
async def payouts(
    program: ReferralProgram = Depends(owner_program), session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    values = list(
        await session.scalars(
            select(ReferralPayout)
            .where(ReferralPayout.referral_program_id == program.id)
            .order_by(ReferralPayout.requested_at.desc())
        )
    )
    return {
        "items": [
            {
                "id": item.id,
                "amount_cents": item.amount_cents,
                "status": item.status,
                "requested_at": item.requested_at,
                "paid_at": item.paid_at,
            }
            for item in values
        ]
    }


@router.post("/payouts/request", status_code=201)
async def payout_request(
    payload: ReferralPayoutRequest,
    program: ReferralProgram = Depends(owner_program),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    if not settings.referral_payouts_enabled:
        raise HTTPException(status_code=403, detail={"code": "referral_payouts_disabled"})
    try:
        payout = await request_payout(
            session,
            program=program,
            amount_cents=payload.amount_cents,
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except WithdrawalError as error:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "available_balance": f"{error.available_cents / 100:.2f}",
                "currency": "EUR",
            },
        ) from error
    value = await balances(session, program.id)
    return {
        "id": payout.id,
        "status": payout.status,
        "available_cents": value.available_cents,
        "reserved_cents": value.reserved_cents,
    }
