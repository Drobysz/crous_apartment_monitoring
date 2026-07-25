from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import structlog
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from arq import cron
from arq.connections import RedisSettings

from app.bot.services import refresh_visible_main_screen
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.crous.client import CrousClient
from app.crous.models import Bounds
from app.db.models import User
from app.db.session import SessionLocal
from app.notifications.service import apply_snapshot, send_change
from app.searches.scheduler import due_search_groups
from app.searches.service import bounds_log_fields, validate_bounds

logger = structlog.get_logger(__name__)


async def monitor_due_searches(_: dict[str, object]) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    crous, bot = CrousClient(settings), Bot(
        settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        async with SessionLocal() as session:
            groups = await due_search_groups(session, datetime.now(UTC))
            for bounds_key, searches in groups.items():
                try:
                    bounds = validate_bounds(Bounds(*bounds_key))
                    items = await crous.search(bounds)
                    # A failed group rolls back only its own association and
                    # notification writes.  The outer session remains usable
                    # for other users/groups in this worker run.
                    async with session.begin_nested():
                        for search in searches:
                            changes = await apply_snapshot(session, search, items)
                            user = await session.get(User, search.user_id)
                            if user:
                                for listing, kind in changes:
                                    await send_change(bot, session, user, search, listing, kind)
                                await refresh_visible_main_screen(bot, session, user)
                            search.next_check_at = datetime.now(UTC) + timedelta(
                                minutes=search.check_interval_minutes,
                                seconds=random.randint(0, 120),
                            )
                except Exception as error:
                    logger.exception(
                        "search_group_failed",
                        search_ids=[search.id for search in searches],
                        reason=str(error),
                        **bounds_log_fields(Bounds(*bounds_key)),
                    )
                    for search in searches:
                        search.consecutive_errors += 1
                        search.next_check_at = datetime.now(UTC) + timedelta(minutes=min(24 * 60, 2 ** min(search.consecutive_errors, 10)))
            await session.commit()
    finally:
        await crous.close(); await bot.session.close()


async def startup(_: dict[str, object]) -> None:
    configure_logging(get_settings().log_level)


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions = [monitor_due_searches]
    cron_jobs = [cron(monitor_due_searches, second={0, 30})]
    on_startup = startup
    keep_result = 0
