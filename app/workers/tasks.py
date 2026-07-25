from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.crous.client import CrousClient
from app.crous.models import Bounds
from app.db.models import User
from app.db.session import SessionLocal
from app.notifications.service import apply_snapshot, send_change
from app.searches.scheduler import due_search_groups


async def monitor_due_searches(_: dict[str, object]) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    crous, bot = CrousClient(settings), Bot(settings.telegram_bot_token.get_secret_value())
    try:
        async with SessionLocal() as session:
            groups = await due_search_groups(session, datetime.now(UTC))
            for bounds_key, searches in groups.items():
                try:
                    items = await crous.search(Bounds(*bounds_key))
                    for search in searches:
                        changes = await apply_snapshot(session, search, items)
                        user = await session.get(User, search.user_id)
                        if user:
                            for listing, kind in changes:
                                await send_change(bot, session, user, search, listing, kind)
                        search.next_check_at = datetime.now(UTC) + timedelta(minutes=search.check_interval_minutes, seconds=random.randint(0, 120))
                except Exception:
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
