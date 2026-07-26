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
from app.core.logging import configure_logging
from app.crous.client import CrousClient
from app.db.models import Search
from app.db.session import SessionLocal
from app.monitoring.locks import SearchLock
from app.monitoring.service import synchronize_search

logger = structlog.get_logger(__name__)


async def enqueue_active_searches(ctx: dict[str, object]) -> None:
    """Schedule independent per-search jobs on a fixed five-minute cadence."""
    settings = get_settings()
    slot = int(datetime.now(UTC).timestamp() // settings.monitoring_interval_seconds)
    async with SessionLocal() as session:
        search_ids = list(await session.scalars(select(Search.id).where(Search.is_active)))
    for search_id in search_ids:
        await ctx["redis"].enqueue_job("sync_search", search_id, _job_id=f"crous-sync:{search_id}:{slot}")  # type: ignore[attr-defined]
    logger.info("search_sync_jobs_enqueued", count=len(search_ids), slot=slot)


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
    cron_jobs = [cron(enqueue_active_searches, minute=set(range(0, 60, 5)), second=0)]
    on_startup = startup
    keep_result = 0
    max_jobs = 10
