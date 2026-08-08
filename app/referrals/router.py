# ruff: noqa: B008
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.schemas import ReferralOwnerExchangeRequest, ReferralPayoutRequest
from app.core.config import Settings, get_settings
from app.db.models import (
    Purchase,
    ReferralCommission,
    ReferralPayout,
    ReferralProgram,
    SubscriptionPlan,
    User,
    UserReferral,
)
from app.db.session import get_session
from app.referrals.service import (
    WithdrawalError,
    balances,
    consume_owner_login_token,
    request_payout,
)

router = APIRouter(prefix="/referral-owner", tags=["referral-owner"])

OWNER_SESSION_COOKIE = "crous_referral_owner_session"
OWNER_SESSION_DURATION = timedelta(hours=8)


def _owner_key(settings: Settings) -> bytes:
    if settings.admin_session_secret is None:
        raise HTTPException(status_code=503, detail={"code": "owner_sessions_unavailable"})
    return settings.admin_session_secret.get_secret_value().encode()


def _encode(program_id: int, settings: Settings) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(
            {
                "pid": program_id,
                "exp": int((datetime.now(UTC) + OWNER_SESSION_DURATION).timestamp()),
            },
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
    owner_session: str | None = Cookie(default=None, alias=OWNER_SESSION_COOKIE),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ReferralProgram:
    if not owner_session:
        raise HTTPException(status_code=401, detail={"code": "owner_authentication_required"})
    program = await session.get(ReferralProgram, _decode(owner_session, settings))
    if program is None or program.deleted_at is not None or not program.is_active:
        raise HTTPException(status_code=401, detail={"code": "owner_session_unavailable"})
    return program


def _set_owner_session(response: Response, program: ReferralProgram, settings: Settings) -> None:
    referral_url = settings.referral_stats_base_url
    secure = bool(referral_url and urlsplit(str(referral_url)).scheme == "https")
    response.set_cookie(
        OWNER_SESSION_COOKIE,
        _encode(program.id, settings),
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
        max_age=int(OWNER_SESSION_DURATION.total_seconds()),
    )


@router.post("/auth/exchange")
async def exchange(
    payload: ReferralOwnerExchangeRequest,
    response: Response,
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
    _set_owner_session(response, program, settings)
    return {"expires_in_seconds": int(OWNER_SESSION_DURATION.total_seconds())}


@router.get("/me")
async def me(program: ReferralProgram = Depends(owner_program)) -> dict[str, object]:
    return {"referral_code": program.referral_code}


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
    period: str = Query(default="month", pattern="^(day|week|month)$"),
    program: ReferralProgram = Depends(owner_program),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    value = await balances(session, program.id)
    attached_users = int(
        await session.scalar(
            select(func.count())
            .select_from(UserReferral)
            .where(UserReferral.referral_program_id == program.id)
        )
        or 0
    )
    commissions = list(
        await session.scalars(
            select(ReferralCommission).where(
                ReferralCommission.referral_program_id == program.id,
                ReferralCommission.status == "earned",
                ReferralCommission.reversal_of_id.is_(None),
            )
        )
    )
    series_values: dict[str, int] = {}
    for commission in commissions:
        timestamp = commission.created_at
        stamp = (
            timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
        )
        if period == "month":
            key = stamp.strftime("%Y-%m")
        elif period == "week":
            key = (stamp.date() - timedelta(days=stamp.weekday())).isoformat()
        else:
            key = stamp.date().isoformat()
        series_values[key] = series_values.get(key, 0) + commission.commission_amount_cents
    return {
        "attached_users": attached_users,
        "pending_cents": value.pending_cents,
        "earned_cents": value.earned_cents,
        "available_cents": value.available_cents,
        "reserved_cents": value.reserved_cents,
        "paid_cents": value.paid_cents,
        "reversed_cents": value.reversed_cents,
        "currency": "EUR",
        "income_series": [
            {"key": key, "amount_cents": amount} for key, amount in sorted(series_values.items())
        ],
    }


@router.get("/purchases")
async def purchases(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    program: ReferralProgram = Depends(owner_program),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    statement = (
        select(ReferralCommission, Purchase, User, SubscriptionPlan)
        .join(Purchase, Purchase.id == ReferralCommission.purchase_id)
        .join(User, User.id == Purchase.user_id)
        .join(SubscriptionPlan, SubscriptionPlan.id == Purchase.subscription_plan_id)
        .where(
            ReferralCommission.referral_program_id == program.id,
            ReferralCommission.purchase_id.is_not(None),
        )
    )
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = (
        await session.execute(
            statement.order_by(Purchase.purchased_at.desc(), Purchase.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": [
            {
                "username": f"@{user.telegram_username}" if user.telegram_username else None,
                "purchased_at": purchase.purchased_at,
                "plan": plan.name,
                "amount_cents": purchase.amount_cents,
                "commission_cents": commission.commission_amount_cents,
                "currency": commission.currency,
                "status": commission.status,
            }
            for commission, purchase, user, plan in rows
        ],
        "meta": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": max(1, (total + page_size - 1) // page_size),
        },
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
