from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Purchase, SubscriptionPlan, User, UserSubscription

FREE = "free"
TRIAL = "trial"
SEASON = "season"
LIFETIME = "lifetime"
PREMIUM_FEATURES = ("advanced_filters", "check_now", "priority_monitoring")


@dataclass(frozen=True)
class EffectiveSubscription:
    plan: SubscriptionPlan
    entitlement: UserSubscription | None


def _virtual_plan(code: str, name: str) -> SubscriptionPlan:
    """Free and Trial are entitlements, not sellable database products."""
    return SubscriptionPlan(code=code, name=name, price_cents=0, is_active=True)


async def ensure_default_plans(session: AsyncSession, settings: Settings | None = None) -> None:
    """Seed only paid products. Existing PostgreSQL prices are never overwritten."""
    settings = settings or get_settings()
    values = ((SEASON, "Season", 1000), (LIFETIME, "Lifetime", 2400))
    existing = {plan.code: plan for plan in (await session.scalars(select(SubscriptionPlan))).all()}
    for code, name, price_cents in values:
        plan = existing.get(code)
        if plan is None:
            session.add(SubscriptionPlan(code=code, name=name, price_cents=price_cents, is_active=True))
        else:
            plan.name = name
    await session.flush()


async def plan_by_code(session: AsyncSession, code: str) -> SubscriptionPlan | None:
    await ensure_default_plans(session)
    if code == FREE:
        return _virtual_plan(FREE, "Free")
    if code == TRIAL:
        return _virtual_plan(TRIAL, "Trial")
    return await session.scalar(
        select(SubscriptionPlan).where(SubscriptionPlan.code == code, SubscriptionPlan.is_active.is_(True))
    )


async def paid_plans(session: AsyncSession) -> list[SubscriptionPlan]:
    await ensure_default_plans(session)
    return list(
        await session.scalars(
            select(SubscriptionPlan)
            .where(SubscriptionPlan.code.in_((SEASON, LIFETIME)), SubscriptionPlan.is_active.is_(True))
            .order_by(SubscriptionPlan.id)
        )
    )


def plan_features(plan: SubscriptionPlan) -> tuple[str, ...]:
    return PREMIUM_FEATURES if plan.code in (TRIAL, SEASON, LIFETIME) else ()


def plan_interval(plan: SubscriptionPlan, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    return settings.premium_monitoring_interval_seconds if plan_features(plan) else settings.free_monitoring_interval_seconds


async def get_effective_subscription(
    session: AsyncSession, user: User, now: datetime | None = None
) -> EffectiveSubscription:
    now = now or datetime.now(UTC)
    await ensure_default_plans(session)
    entitlement = await session.scalar(
        select(UserSubscription)
        .where(
            UserSubscription.user_id == user.id,
            UserSubscription.status == "active",
            UserSubscription.starts_at <= now,
            UserSubscription.ends_at.is_(None) | (UserSubscription.ends_at > now),
        )
        .order_by(UserSubscription.ends_at.is_(None).desc(), UserSubscription.starts_at.desc(), UserSubscription.id.desc())
    )
    if entitlement:
        plan = await session.get(SubscriptionPlan, entitlement.subscription_plan_id)
        if plan:
            return EffectiveSubscription(plan, entitlement)
    return EffectiveSubscription(_virtual_plan(FREE, "Free"), None)


async def get_pending_subscription(
    session: AsyncSession, user: User, now: datetime | None = None
) -> EffectiveSubscription | None:
    now = now or datetime.now(UTC)
    entitlement = await session.scalar(
        select(UserSubscription)
        .where(
            UserSubscription.user_id == user.id,
            UserSubscription.status == "active",
            UserSubscription.starts_at > now,
        )
        .order_by(UserSubscription.starts_at)
    )
    if entitlement is None:
        return None
    plan = await session.get(SubscriptionPlan, entitlement.subscription_plan_id)
    return EffectiveSubscription(plan, entitlement) if plan else None


def has_feature(effective: EffectiveSubscription, feature: str) -> bool:
    return feature in plan_features(effective.plan)


async def can_use_advanced_filters(session: AsyncSession, user: User) -> bool:
    return has_feature(await get_effective_subscription(session, user), "advanced_filters")


async def can_check_now(session: AsyncSession, user: User) -> bool:
    return has_feature(await get_effective_subscription(session, user), "check_now")


async def get_monitoring_interval(session: AsyncSession, user: User) -> int:
    return plan_interval((await get_effective_subscription(session, user)).plan)


def season_window(now: datetime, settings: Settings | None = None) -> tuple[datetime, datetime]:
    settings = settings or get_settings()
    timezone = now.tzinfo or UTC
    start_this_year = datetime.combine(
        date(now.year, settings.season_start_month, settings.season_start_day), time.min, tzinfo=timezone
    )
    end_this_year = datetime.combine(
        date(now.year, settings.season_end_month, settings.season_end_day), time.max, tzinfo=timezone
    )
    if now > end_this_year:
        return start_this_year.replace(year=now.year + 1), end_this_year.replace(year=now.year + 1)
    return start_this_year, end_this_year


def entitlement_dates(
    plan: SubscriptionPlan, now: datetime, settings: Settings | None = None
) -> tuple[datetime, datetime | None]:
    settings = settings or get_settings()
    if plan.code == TRIAL:
        return now, now + timedelta(hours=settings.trial_duration_hours)
    if plan.code == SEASON:
        return season_window(now, settings)
    return now, None


async def activate_subscription(
    session: AsyncSession,
    user: User,
    plan: SubscriptionPlan,
    *,
    source: str,
    purchase: Purchase | None = None,
    now: datetime | None = None,
) -> UserSubscription:
    now = now or datetime.now(UTC)
    starts_at, ends_at = entitlement_dates(plan, now)
    if plan.id is None:
        raise ValueError("Only paid plans can be persisted as entitlements")
    entitlement = UserSubscription(
        user_id=user.id,
        subscription_plan_id=plan.id,
        purchase_id=purchase.id if purchase else None,
        starts_at=starts_at,
        ends_at=ends_at,
        status="active",
        activation_source=source,
    )
    session.add(entitlement)
    await session.flush()
    return entitlement


async def activate_trial(
    session: AsyncSession, user: User, now: datetime | None = None
) -> UserSubscription | None:
    # Trial is represented by a zero-price internal plan only when it is first used.
    if user.trial_used_at is not None:
        return None
    now = now or datetime.now(UTC)
    plan = await session.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == TRIAL))
    if plan is None:
        plan = SubscriptionPlan(code=TRIAL, name="Trial", price_cents=0, is_active=False)
        session.add(plan)
        await session.flush()
    entitlement = await activate_subscription(session, user, plan, source="trial", now=now)
    user.trial_used_at = now
    return entitlement


async def reset_current_subscription(session: AsyncSession, user: User) -> bool:
    """Developer-only test reset: revoke access without mutating purchase history."""
    effective = await get_effective_subscription(session, user)
    if effective.entitlement is None:
        return False
    effective.entitlement.status = "revoked"
    await session.flush()
    return True


async def expire_subscriptions(session: AsyncSession, now: datetime | None = None) -> list[UserSubscription]:
    now = now or datetime.now(UTC)
    expired = list(
        await session.scalars(
            select(UserSubscription).where(
                UserSubscription.status == "active",
                UserSubscription.ends_at.is_not(None),
                UserSubscription.ends_at <= now,
            )
        )
    )
    for entitlement in expired:
        entitlement.status = "expired"
    await session.flush()
    return expired
