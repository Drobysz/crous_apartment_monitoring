from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.security import normalize_username
from app.db.models import (
    AdminAudit,
    Purchase,
    ReferralCommission,
    ReferralOwnerLoginToken,
    ReferralPayout,
    ReferralPayoutAllocation,
    ReferralProgram,
    User,
    UserReferral,
    UserSubscription,
)

DEFAULT_RATE_BASIS_POINTS = 3_000


class ReferralError(ValueError):
    code = "referral_error"


class WithdrawalError(ReferralError):
    def __init__(self, code: str, available_cents: int) -> None:
        self.code, self.available_cents = code, available_cents
        super().__init__(code)


@dataclass(frozen=True)
class ReferralBalances:
    pending_cents: int
    earned_cents: int
    reversed_cents: int
    reserved_cents: int
    paid_cents: int
    available_cents: int


def normalize_referral_code(value: str) -> str:
    code = value.strip()
    if not (3 <= len(code) <= 64) or not code.replace("-", "").replace("_", "").isalnum():
        raise ReferralError("invalid_referral_code")
    return code


async def create_program(
    session: AsyncSession,
    *,
    owner_username: str,
    referral_code: str,
    created_by_admin_id: int,
    commission_rate_basis_points: int = DEFAULT_RATE_BASIS_POINTS,
) -> ReferralProgram:
    owner_display, owner_key = normalize_username(owner_username)
    code = normalize_referral_code(referral_code)
    if not 0 <= commission_rate_basis_points <= 10_000:
        raise ReferralError("invalid_commission_rate")
    program = ReferralProgram(
        referral_code=code,
        owner_telegram_username=owner_display,
        owner_username_key=owner_key,
        commission_rate_basis_points=commission_rate_basis_points,
        created_by_admin_id=created_by_admin_id,
    )
    session.add(program)
    await session.flush()
    session.add(
        AdminAudit(
            actor_admin_id=created_by_admin_id,
            action="referral_created",
            target_type="referral_program",
            target_id=str(program.id),
            metadata_json={"referral_code": code, "owner_username": owner_display},
        )
    )
    return program


async def attribute_first_touch(
    session: AsyncSession, user: User, referral_code: str
) -> UserReferral | None:
    """Insert-once attribution; an integrity race means another valid first touch won."""
    existing = await session.scalar(select(UserReferral).where(UserReferral.user_id == user.id))
    if existing is not None:
        return existing
    program = await session.scalar(
        select(ReferralProgram).where(
            ReferralProgram.referral_code == referral_code,
            ReferralProgram.is_active.is_(True),
            ReferralProgram.deleted_at.is_(None),
        )
    )
    if program is None:
        return None
    referral = UserReferral(
        user_id=user.id, referral_program_id=program.id, attribution_source="telegram_start"
    )
    async with session.begin_nested():
        session.add(referral)
        try:
            await session.flush()
        except IntegrityError:
            # The savepoint releases the failed INSERT and the caller can
            # fetch the first winner without breaking normal onboarding.
            pass
    return await session.scalar(select(UserReferral).where(UserReferral.user_id == user.id))


async def bind_owner(
    session: AsyncSession, program: ReferralProgram, telegram_user_id: int
) -> bool:
    if program.deleted_at is not None or not program.is_active:
        return False
    if program.owner_telegram_user_id is not None:
        return program.owner_telegram_user_id == telegram_user_id
    bound_elsewhere = await session.scalar(
        select(ReferralProgram.id).where(
            ReferralProgram.owner_telegram_user_id == telegram_user_id,
            ReferralProgram.id != program.id,
        )
    )
    if bound_elsewhere is not None:
        return False
    # The unique database constraint is the final guard when two first
    # verifications race. Keep the loser transaction usable for the bot.
    try:
        async with session.begin_nested():
            program.owner_telegram_user_id = telegram_user_id
            await session.flush()
    except IntegrityError:
        return False
    session.add(
        AdminAudit(
            actor_admin_id=None,
            action="referral_owner_bound",
            target_type="referral_program",
            target_id=str(program.id),
            metadata_json={"telegram_user_id": telegram_user_id},
        )
    )
    return True


async def create_commission_for_purchase(
    session: AsyncSession, purchase: Purchase, *, payment_event_id: str | None = None
) -> ReferralCommission | None:
    """Create one immutable earned ledger row for an eligible captured payment."""
    if (
        purchase.status != "paid"
        or purchase.amount_cents is None
        or purchase.amount_cents <= 0
        or purchase.is_test
    ):
        return None
    existing = await session.scalar(
        select(ReferralCommission).where(ReferralCommission.purchase_id == purchase.id)
    )
    if existing is not None:
        return existing
    attribution = await session.scalar(
        select(UserReferral).where(UserReferral.user_id == purchase.user_id)
    )
    if attribution is None:
        return None
    program = await session.get(ReferralProgram, attribution.referral_program_id)
    payer = await session.get(User, purchase.user_id)
    if program is None or payer is None:
        return None
    # Numeric Telegram binding is authoritative for self-referral exclusion.
    if (
        program.owner_telegram_user_id is not None
        and payer.telegram_user_id == program.owner_telegram_user_id
    ):
        return None
    entitlement_source = await session.scalar(
        select(func.count())
        .select_from(UserSubscription)
        .where(
            UserSubscription.purchase_id == purchase.id,
            UserSubscription.activation_source.in_(("admin_lifetime", "complimentary")),
        )
    )
    if entitlement_source:
        return None
    amount = purchase.amount_cents * program.commission_rate_basis_points // 10_000
    commission = ReferralCommission(
        referral_program_id=program.id,
        user_id=purchase.user_id,
        purchase_id=purchase.id,
        payment_event_id=payment_event_id or purchase.stripe_event_id,
        gross_amount_cents=purchase.amount_cents,
        commission_rate_basis_points=program.commission_rate_basis_points,
        commission_amount_cents=amount,
        status="earned",
    )
    session.add(commission)
    await session.flush()
    session.add(
        AdminAudit(
            actor_admin_id=None,
            action="commission_created",
            target_type="referral_commission",
            target_id=str(commission.id),
            metadata_json={
                "referral_program_id": program.id,
                "purchase_id": purchase.id,
                "amount_cents": amount,
            },
        )
    )
    return commission


async def reverse_commission(
    session: AsyncSession, original: ReferralCommission, *, reason: str
) -> ReferralCommission:
    if original.reversal_of_id is not None or original.status == "reversed":
        raise ReferralError("commission_already_reversed")
    reversal = ReferralCommission(
        referral_program_id=original.referral_program_id,
        user_id=original.user_id,
        gross_amount_cents=original.gross_amount_cents,
        commission_rate_basis_points=original.commission_rate_basis_points,
        commission_amount_cents=original.commission_amount_cents,
        status="reversed",
        reversal_of_id=original.id,
        reversed_at=datetime.now(UTC),
    )
    session.add(reversal)
    await session.flush()
    session.add(
        AdminAudit(
            actor_admin_id=None,
            action="commission_reversed",
            target_type="referral_commission",
            target_id=str(reversal.id),
            metadata_json={"original_id": original.id, "reason": reason},
        )
    )
    return reversal


async def balances(session: AsyncSession, program_id: int) -> ReferralBalances:
    commissions = list(
        await session.scalars(
            select(ReferralCommission).where(ReferralCommission.referral_program_id == program_id)
        )
    )
    earned = sum(
        row.commission_amount_cents
        for row in commissions
        if row.status == "earned" and row.reversal_of_id is None
    )
    pending = sum(row.commission_amount_cents for row in commissions if row.status == "pending")
    reversed_amount = sum(
        row.commission_amount_cents for row in commissions if row.status == "reversed"
    )
    allocations = list(
        await session.scalars(
            select(ReferralPayoutAllocation)
            .join(ReferralPayout)
            .where(ReferralPayout.referral_program_id == program_id)
        )
    )
    payout_map = {
        p.id: p
        for p in (
            await session.scalars(
                select(ReferralPayout).where(ReferralPayout.referral_program_id == program_id)
            )
        ).all()
    }
    reserved = sum(
        row.amount_cents
        for row in allocations
        if payout_map[row.payout_id].status in {"requested", "approved", "processing"}
    )
    paid = sum(
        row.amount_cents for row in allocations if payout_map[row.payout_id].status == "paid"
    )
    return ReferralBalances(
        pending,
        earned,
        reversed_amount,
        reserved,
        paid,
        max(0, earned - reversed_amount - reserved - paid),
    )


async def request_payout(
    session: AsyncSession, *, program: ReferralProgram, amount_cents: int, idempotency_key: str
) -> ReferralPayout:
    if amount_cents < 500:
        raise WithdrawalError(
            "withdrawal_below_minimum", (await balances(session, program.id)).available_cents
        )
    # The program row is the per-owner lock used to serialize recomputation and allocations.
    await session.scalar(
        select(ReferralProgram.id).where(ReferralProgram.id == program.id).with_for_update()
    )
    existing = await session.scalar(
        select(ReferralPayout).where(ReferralPayout.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if existing.referral_program_id != program.id or existing.amount_cents != amount_cents:
            raise ReferralError("idempotency_key_conflict")
        return existing
    current = await balances(session, program.id)
    if amount_cents > current.available_cents:
        raise WithdrawalError(
            "withdrawal_amount_exceeds_available_balance", current.available_cents
        )
    payout = ReferralPayout(
        referral_program_id=program.id, amount_cents=amount_cents, idempotency_key=idempotency_key
    )
    session.add(payout)
    await session.flush()
    remaining = amount_cents
    rows = list(
        await session.scalars(
            select(ReferralCommission)
            .where(
                ReferralCommission.referral_program_id == program.id,
                ReferralCommission.status == "earned",
                ReferralCommission.reversal_of_id.is_(None),
            )
            .order_by(ReferralCommission.id)
            .with_for_update()
        )
    )
    allocated = await session.scalars(select(ReferralPayoutAllocation.commission_id))
    used = set(allocated.all())
    for commission in rows:
        if commission.id in used or remaining <= 0:
            continue
        take = min(commission.commission_amount_cents, remaining)
        session.add(
            ReferralPayoutAllocation(
                payout_id=payout.id, commission_id=commission.id, amount_cents=take
            )
        )
        remaining -= take
    if remaining:
        raise ReferralError("insufficient_allocatable_balance")
    await session.flush()
    session.add(
        AdminAudit(
            actor_admin_id=None,
            action="payout_requested",
            target_type="referral_payout",
            target_id=str(payout.id),
            metadata_json={"referral_program_id": program.id, "amount_cents": amount_cents},
        )
    )
    return payout


async def issue_owner_login_token(
    session: AsyncSession, program: ReferralProgram, ttl_minutes: int
) -> str:
    token = secrets.token_urlsafe(32)
    session.add(
        ReferralOwnerLoginToken(
            referral_program_id=program.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
        )
    )
    await session.flush()
    return token


async def consume_owner_login_token(session: AsyncSession, token: str) -> ReferralProgram | None:
    now = datetime.now(UTC)
    value = await session.scalar(
        select(ReferralOwnerLoginToken)
        .where(ReferralOwnerLoginToken.token_hash == hashlib.sha256(token.encode()).hexdigest())
        .with_for_update()
    )
    if value is None or value.used_at is not None:
        return None
    expires_at = value.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        return None
    value.used_at = now
    program = await session.get(ReferralProgram, value.referral_program_id)
    if program is None or program.deleted_at is not None or not program.is_active:
        return None
    return program
