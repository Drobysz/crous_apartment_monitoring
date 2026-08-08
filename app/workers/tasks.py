from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

import structlog
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from arq import Retry, cron, func
from arq.connections import RedisSettings
from sqlalchemy import func as sql_func
from sqlalchemy import select

from app.core.config import get_settings
from app.core.i18n import i18n
from app.core.logging import configure_logging
from app.crous.client import CrousClient
from app.db.models import Listing, Search, SearchListing, UnsubscribedDigestDelivery, User
from app.db.session import SessionLocal
from app.monitoring.locks import SearchLock
from app.monitoring.service import get_active_searches, synchronize_search
from app.restaurants.client import CrousRestaurantClient
from app.restaurants.renderer import menu_text
from app.restaurants.service import due_deliveries, record_daily_statistic, start_delivery
from app.subscriptions.service import (
    expire_subscriptions,
    get_effective_subscription,
    get_monitoring_interval,
    has_feature,
)

logger = structlog.get_logger(__name__)
PARIS = ZoneInfo("Europe/Paris")


async def enqueue_active_searches(ctx: dict[str, object]) -> None:
    """Schedule due searches at the interval granted by each user's entitlement."""
    settings = get_settings()
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        expired = await expire_subscriptions(session, now)
        if expired and settings.telegram_bot_token:
            notice_bot = Bot(
                settings.telegram_bot_token.get_secret_value(),
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            try:
                for entitlement in expired:
                    user = await session.get(User, entitlement.user_id)
                    if (
                        user is None
                        or user.is_blocked
                        or entitlement.expiration_notified_at is not None
                    ):
                        continue
                    try:
                        await notice_bot.send_message(
                            user.telegram_chat_id, i18n.text(user.language, "subscription-expired")
                        )
                    except Exception as error:
                        logger.warning(
                            "subscription_expiration_notification_failed",
                            user_id=entitlement.user_id,
                            reason=str(error),
                        )
                    else:
                        entitlement.expiration_notified_at = now
            finally:
                await notice_bot.session.close()
        searches = await get_active_searches(session)
        selected: list[tuple[int, int]] = []
        for search, user in searches:
            interval = await get_monitoring_interval(session, user)
            if (
                search.last_checked_at is None
                or (now - search.last_checked_at).total_seconds() >= interval
            ):
                selected.append((search.id, int(now.timestamp() // interval)))
        await session.commit()
    redis = cast(Any, ctx["redis"])
    for search_id, slot in selected:
        await redis.enqueue_job("sync_search", search_id, _job_id=f"crous-sync:{search_id}:{slot}")
    logger.info("search_sync_jobs_enqueued", count=len(selected))


async def _record_failure(search_id: int) -> None:
    async with SessionLocal() as session:
        search = await session.get(Search, search_id)
        if search:
            search.last_checked_at = datetime.now(UTC)
            search.consecutive_errors += 1
            await session.commit()


async def sync_search(ctx: dict[str, object], search_id: int) -> None:
    """One bounded, retryable search job. A failed user cannot block others."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    correlation_id = f"worker:{ctx.get('job_id', search_id)}"
    async with SearchLock(
        ctx["redis"], search_id, settings.monitoring_lock_ttl_seconds
    ) as acquired:
        if not acquired:
            logger.info(
                "search_sync_skipped_locked", correlation_id=correlation_id, search_id=search_id
            )
            return
        crous = CrousClient(settings)
        bot = Bot(
            settings.telegram_bot_token.get_secret_value(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            result = await synchronize_search(
                SessionLocal, bot, crous, search_id, correlation_id=correlation_id
            )
            logger.info(
                "search_sync_finished",
                correlation_id=correlation_id,
                search_id=search_id,
                result=result,
            )
        except Exception as error:
            await _record_failure(search_id)
            job_try = ctx.get("job_try", 1)
            attempt = job_try if isinstance(job_try, int) else 1
            logger.exception(
                "search_sync_failed",
                correlation_id=correlation_id,
                search_id=search_id,
                attempt=attempt,
                reason=str(error),
            )
            if attempt < settings.monitoring_max_retries:
                raise Retry(
                    defer=settings.monitoring_retry_base_seconds * (2 ** (attempt - 1))
                ) from error
            raise
        finally:
            await crous.close()
            await bot.session.close()


async def startup(_: dict[str, object]) -> None:
    configure_logging(get_settings().log_level)


async def enqueue_daily_notifications(ctx: dict[str, object]) -> None:
    local = datetime.now(UTC).astimezone(PARIS)
    redis = cast(Any, ctx["redis"])
    if local.hour == 20 and local.minute == 0:
        await redis.enqueue_job(
            "send_housing_statistics",
            local.date().isoformat(),
            _job_id=f"housing-statistics:{local.date().isoformat()}",
        )
    await redis.enqueue_job(
        "deliver_restaurant_menus", _job_id=f"restaurant-delivery:{local:%Y-%m-%d:%H:%M}"
    )


async def send_housing_statistics(_: dict[str, object], day: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    bot = Bot(
        settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        async with SessionLocal() as session:
            rows = await get_active_searches(session)
            for search, user in rows:
                cheapest, highest, count = (
                    await session.execute(
                        select(
                            sql_func.min(Listing.price_cents),
                            sql_func.max(Listing.price_cents),
                            sql_func.count(sql_func.distinct(Listing.id)),
                        )
                        .select_from(SearchListing)
                        .join(Listing, Listing.id == SearchListing.listing_id)
                        .where(
                            SearchListing.search_id == search.id,
                            SearchListing.is_currently_available.is_(True),
                        )
                    )
                ).one()
                if (
                    await record_daily_statistic(
                        session,
                        search,
                        datetime.fromisoformat(day).date(),
                        cheapest,
                        highest,
                        int(count or 0),
                    )
                    is None
                ):
                    continue

                def money(value: int | None) -> str:
                    return "—" if value is None else f"€{value // 100}.{value % 100:02d}"

                try:
                    await bot.send_message(
                        user.telegram_chat_id,
                        i18n.text(
                            user.language,
                            "daily-statistics-message",
                            cheapest=money(cheapest),
                            highest=money(highest),
                            count=int(count or 0),
                        ),
                    )
                except Exception as error:
                    logger.warning(
                        "housing_statistics_notification_failed",
                        search_id=search.id,
                        reason=str(error),
                    )
            await session.commit()
    finally:
        await bot.session.close()


async def deliver_restaurant_menus(_: dict[str, object]) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    now, bot, client = (
        datetime.now(UTC),
        Bot(
            settings.telegram_bot_token.get_secret_value(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        ),
        CrousRestaurantClient(),
    )
    try:
        async with SessionLocal() as session:
            for user, _subscription, favorite in await due_deliveries(session, now):
                delivery = await start_delivery(session, user, favorite, now)
                if delivery is None:
                    continue
                try:
                    message = await bot.send_message(
                        user.telegram_chat_id,
                        menu_text(
                            await client.menu(
                                favorite.restaurant_code, now.astimezone(PARIS).date()
                            ),
                            user.language,
                        ),
                    )
                except Exception as error:
                    delivery.status, delivery.error = "failed", str(error)
                else:
                    delivery.status, delivery.telegram_message_id, delivery.sent_at = (
                        "sent",
                        message.message_id,
                        now,
                    )
            await session.commit()
    finally:
        await client.close()
        await bot.session.close()


async def send_unsubscribed_digest(_: dict[str, object]) -> None:
    """Send at most one promotional country digest per eligible user and UTC slot."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    now = datetime.now(UTC)
    period_key = int(now.timestamp() // (settings.unsubscribed_digest_interval_hours * 3600))
    bot = Bot(
        settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        async with SessionLocal() as session:
            total = int(
                await session.scalar(
                    select(sql_func.count())
                    .select_from(Listing)
                    .where(
                        Listing.first_seen_at
                        >= now.replace(hour=0, minute=0, second=0, microsecond=0)
                    )
                )
                or 0
            )
            departments = list(
                (
                    await session.execute(
                        select(sql_func.substr(Listing.postal_code, 1, 2), sql_func.count())
                        .where(
                            Listing.first_seen_at
                            >= now.replace(hour=0, minute=0, second=0, microsecond=0),
                            Listing.postal_code.is_not(None),
                        )
                        .group_by(sql_func.substr(Listing.postal_code, 1, 2))
                        .order_by(sql_func.count().desc())
                        .limit(5)
                    )
                ).all()
            )
            top_departments = ", ".join(str(row[0]) for row in departments if row[0]) or "—"
            users = list(
                await session.scalars(
                    select(User).where(
                        User.is_blocked.is_(False),
                        User.digest_opted_out.is_(False),
                        User.telegram_chat_id.is_not(None),
                    )
                )
            )
            for user in users:
                if user.language not in {"fr", "en", "ru", "uk", "tr", "fa", "ar"}:
                    continue
                if has_feature(
                    await get_effective_subscription(session, user, now), "priority_monitoring"
                ):
                    continue
                delivery = UnsubscribedDigestDelivery(user_id=user.id, period_key=period_key)
                async with session.begin_nested():
                    session.add(delivery)
                    try:
                        await session.flush()
                    except Exception:
                        continue
                # Recheck subscription immediately before an external send.
                if (
                    has_feature(
                        await get_effective_subscription(session, user, now), "priority_monitoring"
                    )
                    or user.digest_opted_out
                ):
                    delivery.status = "skipped"
                    continue
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=i18n.text(user.language, "subscription"),
                                callback_data="digest:subscription",
                            ),
                            InlineKeyboardButton(
                                text=i18n.text(user.language, "housing-monitoring"),
                                callback_data="digest:housing",
                            ),
                        ],
                        [
                            InlineKeyboardButton(
                                text=i18n.text(user.language, "digest-stop"),
                                callback_data="digest:stop",
                            )
                        ],
                    ]
                )
                try:
                    await bot.send_message(
                        user.telegram_chat_id,
                        i18n.text(
                            user.language,
                            "unsubscribed-digest",
                            total_today=total,
                            top_departments=top_departments,
                        ),
                        reply_markup=keyboard,
                    )
                except Exception as error:
                    delivery.status, delivery.error, delivery.attempts = (
                        "failed",
                        str(error)[:500],
                        delivery.attempts + 1,
                    )
                else:
                    delivery.status, delivery.sent_at = "sent", now
            await session.commit()
    finally:
        await bot.session.close()


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions = [
        func(sync_search, max_tries=get_settings().monitoring_max_retries),
        send_housing_statistics,
        deliver_restaurant_menus,
        send_unsubscribed_digest,
    ]
    cron_jobs = [
        cron(enqueue_active_searches, minute=set(range(0, 60, 1)), second=0),
        cron(enqueue_daily_notifications, minute=set(range(0, 60, 1)), second=5),
        cron(send_unsubscribed_digest, hour={0, 10, 20}, minute=10, second=0),
    ]
    on_startup = startup
    keep_result = 0
    max_jobs = 10
