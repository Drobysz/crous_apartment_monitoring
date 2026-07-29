from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from math import ceil

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.schemas import (
    AdminResponse,
    BuyerResponse,
    DashboardResponse,
    PageMeta,
    PaidUserResponse,
    RevenuePoint,
    TransactionResponse,
)
from app.db.models import Admin, Purchase, Search, SubscriptionPlan, User, UserSubscription


def page_meta(page: int, page_size: int, total: int) -> PageMeta:
    return PageMeta(page=page, page_size=page_size, total=total, pages=max(1, ceil(total / page_size)))


def admin_response(admin: Admin) -> AdminResponse:
    return AdminResponse(
        id=admin.id,
        name=admin.name,
        username=admin.username,
        role=admin.role,
        is_active=admin.is_active,
        created_at=admin.created_at,
        last_login_at=admin.last_login_at,
    )


def user_handle(user: User) -> str | None:
    username = getattr(user, "telegram_username", None)
    return f"@{username}" if username else None


def _paid_purchase_conditions(start: datetime, end: datetime) -> tuple[object, ...]:
    return (
        Purchase.status == "paid",
        Purchase.is_test.is_(False),
        Purchase.purchased_at.is_not(None),
        Purchase.purchased_at >= start,
        Purchase.purchased_at < end,
    )


def _period_bounds(period: str, now: datetime) -> tuple[datetime, datetime, int, str]:
    today = now.date()
    if period == "week":
        start = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time(), tzinfo=UTC)
        return start, start + timedelta(days=7), 7, "day"
    if period == "year":
        start = datetime(now.year, 1, 1, tzinfo=UTC)
        return start, datetime(now.year + 1, 1, 1, tzinfo=UTC), 12, "month"
    if period != "month":
        raise ValueError("period must be week, month, or year")
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    end = datetime(now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1, 1, tzinfo=UTC)
    return start, end, (end.date() - start.date()).days, "day"


def _period_key(value: datetime, kind: str) -> str:
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.strftime("%Y-%m") if kind == "month" else normalized.date().isoformat()


def _period_keys(start: datetime, count: int, kind: str) -> list[str]:
    if kind == "day":
        return [(start + timedelta(days=offset)).date().isoformat() for offset in range(count)]
    keys: list[str] = []
    current = start
    for _ in range(count):
        keys.append(current.strftime("%Y-%m"))
        current = datetime(current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1, 1, tzinfo=UTC)
    return keys


async def revenue_dashboard(session: AsyncSession, period: str, now: datetime | None = None) -> DashboardResponse:
    now = now or datetime.now(UTC)
    start, end, bucket_count, bucket_kind = _period_bounds(period, now)
    total_users = int(await session.scalar(select(func.count()).select_from(User)) or 0)
    active_paid_subscribers = int(
        await session.scalar(
            select(func.count(func.distinct(UserSubscription.user_id)))
            .join(SubscriptionPlan, SubscriptionPlan.id == UserSubscription.subscription_plan_id)
            .where(
                UserSubscription.status == "active",
                UserSubscription.starts_at <= now,
                or_(UserSubscription.ends_at.is_(None), UserSubscription.ends_at > now),
                SubscriptionPlan.price_cents > 0,
            )
        )
        or 0
    )
    active_monitoring_anchors = int(
        await session.scalar(select(func.count()).select_from(Search).where(Search.is_active.is_(True))) or 0
    )
    paid_rows = (
        await session.execute(
            select(Purchase.purchased_at, Purchase.amount_cents).where(*_paid_purchase_conditions(start, end))
        )
    ).all()
    values: dict[str, int] = defaultdict(int)
    for purchased_at, amount_cents in paid_rows:
        if purchased_at is not None and amount_cents is not None:
            values[_period_key(purchased_at, bucket_kind)] += amount_cents
    series = [RevenuePoint(key=key, amount_cents=values[key]) for key in _period_keys(start, bucket_count, bucket_kind)]
    return DashboardResponse(
        total_users=total_users,
        active_paid_subscribers=active_paid_subscribers,
        active_monitoring_anchors=active_monitoring_anchors,
        revenue_cents=sum(point.amount_cents for point in series),
        revenue_series=series,
    )


async def recent_buyers(session: AsyncSession, limit: int = 10) -> list[BuyerResponse]:
    rows = (
        await session.execute(
            select(Purchase, User, SubscriptionPlan)
            .join(User, User.id == Purchase.user_id)
            .join(SubscriptionPlan, SubscriptionPlan.id == Purchase.subscription_plan_id)
            .where(Purchase.status == "paid", Purchase.is_test.is_(False))
            .order_by(Purchase.purchased_at.desc(), Purchase.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        BuyerResponse(
            purchase_id=purchase.id,
            username=user_handle(user),
            plan=plan.name,
            amount_cents=purchase.amount_cents or 0,
            purchased_at=purchase.purchased_at,
            status=purchase.status,
        )
        for purchase, user, plan in rows
    ]


async def list_admins(session: AsyncSession, query: str | None, page: int, page_size: int) -> tuple[list[AdminResponse], PageMeta]:
    statement: Select[tuple[Admin]] = select(Admin)
    if query:
        term = f"%{query.casefold()}%"
        statement = statement.where(or_(func.lower(Admin.name).like(term), Admin.username_key.like(term)))
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = (
        await session.scalars(statement.order_by(Admin.created_at.desc(), Admin.id.desc()).offset((page - 1) * page_size).limit(page_size))
    ).all()
    return [admin_response(admin) for admin in rows], page_meta(page, page_size, total)


def _paid_user_statement(now: datetime, query: str | None) -> Select[tuple[UserSubscription, User, SubscriptionPlan, int, datetime | None]]:
    ranking = (
        select(
            UserSubscription.id.label("subscription_id"),
            func.row_number()
            .over(
                partition_by=UserSubscription.user_id,
                order_by=(UserSubscription.starts_at.desc(), UserSubscription.id.desc()),
            )
            .label("rank"),
        )
        .join(SubscriptionPlan, SubscriptionPlan.id == UserSubscription.subscription_plan_id)
        .where(
            UserSubscription.status == "active",
            UserSubscription.starts_at <= now,
            or_(UserSubscription.ends_at.is_(None), UserSubscription.ends_at > now),
            SubscriptionPlan.code != "free",
        )
        .subquery()
    )
    active_searches = (
        select(Search.user_id.label("user_id"), func.count(Search.id).label("active_count"))
        .where(Search.is_active.is_(True))
        .group_by(Search.user_id)
        .subquery()
    )
    last_payment = (
        select(Purchase.user_id.label("user_id"), func.max(Purchase.purchased_at).label("last_payment_at"))
        .where(Purchase.status == "paid")
        .group_by(Purchase.user_id)
        .subquery()
    )
    statement = (
        select(
            UserSubscription,
            User,
            SubscriptionPlan,
            func.coalesce(active_searches.c.active_count, 0).label("active_count"),
            last_payment.c.last_payment_at,
        )
        .join(ranking, and_(ranking.c.subscription_id == UserSubscription.id, ranking.c.rank == 1))
        .join(User, User.id == UserSubscription.user_id)
        .join(SubscriptionPlan, SubscriptionPlan.id == UserSubscription.subscription_plan_id)
        .outerjoin(active_searches, active_searches.c.user_id == User.id)
        .outerjoin(last_payment, last_payment.c.user_id == User.id)
    )
    if query:
        term = f"%{query.casefold().lstrip('@')}%"
        statement = statement.where(func.lower(User.telegram_username).like(term))
    return statement


def _paid_user_response(
    subscription: UserSubscription,
    user: User,
    plan: SubscriptionPlan,
    active_count: int,
    last_payment_at: datetime | None,
) -> PaidUserResponse:
    return PaidUserResponse(
        user_id=user.id,
        username=user_handle(user),
        current_plan=plan.name,
        starts_at=subscription.starts_at,
        ends_at=subscription.ends_at,
        status=subscription.status,
        last_payment_at=last_payment_at,
        active_monitoring_count=int(active_count),
    )


async def list_paid_users(session: AsyncSession, query: str | None, page: int, page_size: int) -> tuple[list[PaidUserResponse], PageMeta]:
    statement = _paid_user_statement(datetime.now(UTC), query)
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = (
        await session.execute(
            statement.order_by(UserSubscription.starts_at.desc(), UserSubscription.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [_paid_user_response(*row) for row in rows], page_meta(page, page_size, total)


async def paid_user_details(session: AsyncSession, user_id: int) -> tuple[PaidUserResponse, User, list[Search]] | None:
    statement = _paid_user_statement(datetime.now(UTC), None).where(User.id == user_id)
    row = (await session.execute(statement)).first()
    if row is None:
        return None
    subscription, user, plan, active_count, last_payment_at = row
    searches = (await session.scalars(select(Search).where(Search.user_id == user.id).order_by(Search.id.desc()))).all()
    return _paid_user_response(subscription, user, plan, active_count, last_payment_at), user, list(searches)


def transaction_response(purchase: Purchase, user: User, plan: SubscriptionPlan) -> TransactionResponse:
    return TransactionResponse(
        id=purchase.id,
        username=user_handle(user),
        plan=plan.name,
        amount_cents=purchase.amount_cents,
        status=purchase.status,
        is_test=purchase.is_test,
        stripe_checkout_session_id=purchase.stripe_checkout_session_id,
        stripe_payment_intent_id=purchase.stripe_payment_intent_id,
        purchased_at=purchase.purchased_at,
        created_at=purchase.created_at,
    )


async def list_transactions(session: AsyncSession, query: str | None, page: int, page_size: int) -> tuple[list[TransactionResponse], PageMeta]:
    statement = select(Purchase, User, SubscriptionPlan).join(User, User.id == Purchase.user_id).join(SubscriptionPlan, SubscriptionPlan.id == Purchase.subscription_plan_id)
    if query:
        term = f"%{query.casefold().lstrip('@')}%"
        statement = statement.where(
            or_(
                func.lower(User.telegram_username).like(term),
                Purchase.stripe_checkout_session_id.ilike(f"%{query}%"),
                Purchase.stripe_payment_intent_id.ilike(f"%{query}%"),
            )
        )
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = (
        await session.execute(
            statement.order_by(Purchase.created_at.desc(), Purchase.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    return [transaction_response(*row) for row in rows], page_meta(page, page_size, total)


async def transaction_details(session: AsyncSession, transaction_id: int) -> tuple[TransactionResponse, Purchase] | None:
    row = (
        await session.execute(
            select(Purchase, User, SubscriptionPlan)
            .join(User, User.id == Purchase.user_id)
            .join(SubscriptionPlan, SubscriptionPlan.id == Purchase.subscription_plan_id)
            .where(Purchase.id == transaction_id)
        )
    ).first()
    return (transaction_response(*row), row[0]) if row else None
