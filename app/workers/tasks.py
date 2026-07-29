from __future__ import annotations

from datetime import UTC, datetime

import structlog
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from arq import Retry, cron, func
from arq.connections import RedisSettings
from sqlalchemy import select

from app.core.config import get_settings
from app.core.i18n import i18n
from app.core.logging import configure_logging
from app.crous.client import CrousClient
from app.db.models import Search, User
from app.db.session import SessionLocal
from app.monitoring.locks import SearchLock
from app.monitoring.service import synchronize_search
from app.subscriptions.service import expire_subscriptions, get_monitoring_interval

logger = structlog.get_logger(__name__)


async def enqueue_active_searches(ctx: dict[str, object]) -> None:
    """Schedule due searches at the interval granted by each user's entitlement."""
    settings = get_settings()
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        expired = await expire_subscriptions(session, now)
        if expired and settings.telegram_bot_token:
            notice_bot = Bot(settings.telegram_bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            try:
                for entitlement in expired:
                    user = await session.get(User, entitlement.user_id)
                    if user is None or user.is_blocked or entitlement.expiration_notified_at is not None:
                        continue
                    try:
                        await notice_bot.send_message(user.telegram_chat_id, i18n.text(user.language, "subscription-expired"))
                    except Exception as error:
                        logger.warning("subscription_expiration_notification_failed", user_id=entitlement.user_id, reason=str(error))
                    else:
                        entitlement.expiration_notified_at = now
            finally:
                await notice_bot.session.close()
        searches = (await session.execute(select(Search, User).join(User, User.id == Search.user_id).where(Search.is_active, User.is_blocked.is_(False)))).all()
        selected: list[tuple[int, int]] = []
        for search, user in searches:
            interval = await get_monitoring_interval(session, user)
            if search.last_checked_at is None or (now - search.last_checked_at).total_seconds() >= interval:
                selected.append((search.id, int(now.timestamp() // interval)))
        await session.commit()
    for search_id, slot in selected:
        await ctx["redis"].enqueue_job("sync_search", search_id, _job_id=f"crous-sync:{search_id}:{slot}")  # type: ignore[attr-defined]
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
    async with SearchLock(ctx["redis"], search_id, settings.monitoring_lock_ttl_seconds) as acquired:
        if not acquired:
            logger.info("search_sync_skipped_locked", correlation_id=correlation_id, search_id=search_id)
            return
        crous = CrousClient(settings)
        bot = Bot(settings.telegram_bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        try:
            result = await synchronize_search(SessionLocal, bot, crous, search_id, correlation_id=correlation_id)
            logger.info("search_sync_finished", correlation_id=correlation_id, search_id=search_id, result=result)
        except Exception as error:
            await _record_failure(search_id)
            job_try = ctx.get("job_try", 1)
            attempt = job_try if isinstance(job_try, int) else 1
            logger.exception("search_sync_failed", correlation_id=correlation_id, search_id=search_id, attempt=attempt, reason=str(error))
            if attempt < settings.monitoring_max_retries:
                raise Retry(defer=settings.monitoring_retry_base_seconds * (2 ** (attempt - 1))) from error
            raise
        finally:
            await crous.close()
            await bot.session.close()


async def startup(_: dict[str, object]) -> None:
    configure_logging(get_settings().log_level)


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions = [func(sync_search, max_tries=get_settings().monitoring_max_retries)]
    cron_jobs = [cron(enqueue_active_searches, minute=set(range(0, 60, 1)), second=0)]
    on_startup = startup
    keep_result = 0
    max_jobs = 10
