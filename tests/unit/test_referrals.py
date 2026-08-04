from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    Admin,
    Base,
    Purchase,
    ReferralOwnerLoginToken,
    ReferralProgram,
    SubscriptionPlan,
    User,
    UserReferral,
)
from app.referrals.service import (
    WithdrawalError,
    attribute_first_touch,
    balances,
    bind_owner,
    consume_owner_login_token,
    create_commission_for_purchase,
    create_program,
    issue_owner_login_token,
    request_payout,
)
from app.reports.service import ReportCooldownError, create_report


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as value:
        yield value
    await engine.dispose()


async def _program(session: AsyncSession):
    admin = Admin(name="Owner", username="@owner", username_key="owner", password_hash="hash")
    session.add(admin)
    await session.flush()
    return await create_program(
        session, owner_username="@creator", referral_code="creator-1", created_by_admin_id=admin.id
    )


@pytest.mark.asyncio
async def test_first_touch_is_permanent_and_commission_is_idempotent(session: AsyncSession) -> None:
    program = await _program(session)
    user = User(telegram_user_id=100, telegram_chat_id=101, language="en")
    plan = SubscriptionPlan(code="season-test", name="Season", price_cents=2000)
    session.add_all((user, plan))
    await session.flush()
    first = await attribute_first_touch(session, user, "creator-1")
    second = await attribute_first_touch(session, user, "other-code")
    assert first is not None and second is not None and first.id == second.id
    purchase = Purchase(
        user_id=user.id,
        subscription_plan_id=plan.id,
        stripe_checkout_session_id="cs_referral",
        stripe_event_id="evt_referral",
        amount_cents=2000,
        status="paid",
        is_test=False,
        purchased_at=datetime.now(UTC),
        processed_at=datetime.now(UTC),
    )
    session.add(purchase)
    await session.flush()
    commission = await create_commission_for_purchase(session, purchase)
    duplicate = await create_commission_for_purchase(session, purchase)
    assert commission is not None and duplicate is not None
    assert commission.id == duplicate.id
    assert commission.commission_amount_cents == 600
    assert (await balances(session, program.id)).available_cents == 600


@pytest.mark.asyncio
async def test_payout_reservation_enforces_minimum_balance_and_idempotency(
    session: AsyncSession,
) -> None:
    program = await _program(session)
    user = User(telegram_user_id=100, telegram_chat_id=101, language="en")
    plan = SubscriptionPlan(code="lifetime-test", name="Lifetime", price_cents=2000)
    session.add_all((user, plan))
    await session.flush()
    await attribute_first_touch(session, user, "creator-1")
    purchase = Purchase(
        user_id=user.id,
        subscription_plan_id=plan.id,
        stripe_checkout_session_id="cs_payout",
        stripe_event_id="evt_payout",
        amount_cents=2000,
        status="paid",
        is_test=False,
        purchased_at=datetime.now(UTC),
        processed_at=datetime.now(UTC),
    )
    session.add(purchase)
    await session.flush()
    await create_commission_for_purchase(session, purchase)
    with pytest.raises(WithdrawalError) as below_minimum:
        await request_payout(session, program=program, amount_cents=499, idempotency_key="a" * 16)
    assert below_minimum.value.code == "withdrawal_below_minimum"
    payout = await request_payout(
        session, program=program, amount_cents=500, idempotency_key="b" * 16
    )
    assert payout.status == "requested"
    assert (await balances(session, program.id)).available_cents == 100
    assert (
        await request_payout(session, program=program, amount_cents=500, idempotency_key="b" * 16)
    ).id == payout.id
    with pytest.raises(WithdrawalError) as too_high:
        await request_payout(session, program=program, amount_cents=500, idempotency_key="c" * 16)
    assert too_high.value.code == "withdrawal_amount_exceeds_available_balance"


@pytest.mark.asyncio
async def test_report_cooldown_uses_exact_hour_boundary_and_user_scope(
    session: AsyncSession,
) -> None:
    first = User(telegram_user_id=201, telegram_chat_id=201, language="en")
    second = User(telegram_user_id=202, telegram_chat_id=202, language="en")
    session.add_all((first, second))
    await session.flush()
    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    await create_report(session, first, "First", None, now=now)
    with pytest.raises(ReportCooldownError) as blocked:
        await create_report(session, first, "Again", None, now=now)
    assert blocked.value.remaining_seconds == 3600
    await create_report(session, second, "Independent", None, now=now)
    await create_report(session, first, "At boundary", None, now=now.replace(hour=13))


@pytest.mark.asyncio
async def test_soft_deleted_referral_keeps_history_but_rejects_new_attribution(
    session: AsyncSession,
) -> None:
    program = await _program(session)
    attributed_user = User(telegram_user_id=301, telegram_chat_id=301, language="en")
    later_user = User(telegram_user_id=302, telegram_chat_id=302, language="en")
    session.add_all((attributed_user, later_user))
    await session.flush()
    attribution = await attribute_first_touch(session, attributed_user, program.referral_code)
    assert attribution is not None

    program.deleted_at = datetime.now(UTC)
    program.is_active = False
    await session.flush()

    assert await attribute_first_touch(session, later_user, program.referral_code) is None
    stored = await session.scalar(select(UserReferral).where(UserReferral.id == attribution.id))
    assert stored is not None and stored.referral_program_id == program.id


@pytest.mark.asyncio
async def test_owner_binding_uses_numeric_identity_and_prevents_duplicate_ownership(
    session: AsyncSession,
) -> None:
    first = await _program(session)
    second = ReferralProgram(
        referral_code="creator-2",
        owner_telegram_username="@second",
        owner_username_key="second",
        created_by_admin_id=first.created_by_admin_id,
    )
    session.add(second)
    await session.flush()

    assert await bind_owner(session, first, 4001)
    first.owner_telegram_username = "@renamed"
    first.owner_username_key = "renamed"
    assert await bind_owner(session, first, 4001)
    assert not await bind_owner(session, first, 4002)
    assert not await bind_owner(session, second, 4001)


@pytest.mark.asyncio
async def test_expired_or_revoked_owner_login_tokens_are_rejected(session: AsyncSession) -> None:
    program = await _program(session)
    token = await issue_owner_login_token(session, program, ttl_minutes=15)
    stored = await session.scalar(
        select(ReferralOwnerLoginToken).where(
            ReferralOwnerLoginToken.referral_program_id == program.id
        )
    )
    assert stored is not None
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await consume_owner_login_token(session, token) is None

    fresh_token = await issue_owner_login_token(session, program, ttl_minutes=15)
    program.is_active = False
    assert await consume_owner_login_token(session, fresh_token) is None
