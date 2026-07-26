from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.cards import send_accommodation_card
from app.bot.services import refresh_visible_main_screen
from app.core.i18n import i18n
from app.crous.client import CrousClient
from app.crous.models import Bounds
from app.db.models import Search, SearchDisplayGroup, SearchDisplayMessage, User
from app.notifications.service import apply_snapshot
from app.searches.service import validate_bounds

from .snapshot import canonical_snapshot

logger = structlog.get_logger(__name__)


class SnapshotDeliveryError(RuntimeError):
    pass


async def _active_group(session: AsyncSession, search_id: int) -> SearchDisplayGroup | None:
    return await session.scalar(
        select(SearchDisplayGroup)
        .where(SearchDisplayGroup.search_id == search_id, SearchDisplayGroup.status == "active")
        .order_by(SearchDisplayGroup.id.desc())
    )


async def _cleanup_group(bot: Bot, session: AsyncSession, group: SearchDisplayGroup) -> None:
    messages = (await session.scalars(select(SearchDisplayMessage).where(SearchDisplayMessage.display_group_id == group.id))).all()
    for message in messages:
        try:
            await bot.delete_message(group.telegram_chat_id, message.telegram_message_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            # A deleted/blocked message is terminal; retaining its row would
            # make future cleanup retry forever.
            pass
        finally:
            await session.delete(message)
    group.status = "retired"
    group.retired_at = datetime.now(UTC)


async def recover_pending_groups(bot: Bot, session: AsyncSession, search_id: int) -> None:
    pending = (await session.scalars(
        select(SearchDisplayGroup).where(SearchDisplayGroup.search_id == search_id, SearchDisplayGroup.status == "pending")
    )).all()
    for group in pending:
        await _cleanup_group(bot, session, group)


async def synchronize_search(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    crous: CrousClient,
    search_id: int,
    *,
    correlation_id: str | None = None,
) -> str:
    """Fetch a complete result set and replace a search's displayed list iff it changed.

    Returns ``changed``, ``unchanged`` or raises. The caller owns the per-search
    distributed lock, which keeps manual and worker-triggered runs idempotent.
    """
    correlation_id = correlation_id or str(uuid4())
    async with session_factory() as session:
        search = await session.get(Search, search_id)
        if search is None or not search.is_active:
            return "inactive"
        user = await session.get(User, search.user_id)
        if user is None or user.is_blocked:
            return "inactive"
        bounds = validate_bounds(Bounds(search.bounds_west, search.bounds_north, search.bounds_east, search.bounds_south))
        logger.info("search_sync_fetch_started", correlation_id=correlation_id, search_id=search.id, user_id=user.telegram_user_id)
        raw_items = await crous.search(bounds, correlation_id=correlation_id)
        items, fingerprint = canonical_snapshot(raw_items)
        logger.info("search_sync_fetch_completed", correlation_id=correlation_id, search_id=search.id, raw_count=len(raw_items), listing_count=len(items), fingerprint=fingerprint)

        await recover_pending_groups(bot, session, search.id)
        active = await _active_group(session, search.id)
        now = datetime.now(UTC)
        if active and active.fingerprint == fingerprint:
            search.last_checked_at = search.last_success_at = now
            search.consecutive_errors = 0
            await session.commit()
            logger.info("search_snapshot_unchanged", correlation_id=correlation_id, search_id=search.id, fingerprint=fingerprint)
            return "unchanged"

        pending = SearchDisplayGroup(
            search_id=search.id,
            telegram_chat_id=user.telegram_chat_id,
            fingerprint=fingerprint,
            listing_count=len(items),
            status="pending",
        )
        session.add(pending)
        await session.commit()

        try:
            if items:
                for item in items:
                    message_id = await send_accommodation_card(bot, user.telegram_chat_id, item, user.language, now)
                    session.add(SearchDisplayMessage(display_group_id=pending.id, telegram_message_id=message_id, message_kind="card"))
                    await session.commit()  # recoverable even if the process exits mid-group
                    logger.info("search_display_card_sent", correlation_id=correlation_id, search_id=search.id, message_id=message_id, external_id=item.external_id)
            else:
                empty = await bot.send_message(user.telegram_chat_id, i18n.text(user.language, "no-listings"))
                session.add(SearchDisplayMessage(display_group_id=pending.id, telegram_message_id=empty.message_id, message_kind="empty"))
                await session.commit()
        except Exception as error:
            await _cleanup_group(bot, session, pending)
            pending.status = "failed"
            search.consecutive_errors += 1
            search.last_checked_at = datetime.now(UTC)
            await session.commit()
            raise SnapshotDeliveryError(str(error)) from error

        # New messages are known to exist before the old group is retired.
        await apply_snapshot(session, search, items)
        pending.status, pending.activated_at = "active", now
        if active:
            active.status, active.retired_at = "retiring", now
        search.snapshot_fingerprint = fingerprint
        search.last_checked_at = search.last_success_at = search.last_changed_at = now
        search.consecutive_errors = 0
        await session.commit()
        logger.info("search_snapshot_activated", correlation_id=correlation_id, search_id=search.id, fingerprint=fingerprint, listing_count=len(items))

        if active:
            await _cleanup_group(bot, session, active)
            await session.commit()
        await refresh_visible_main_screen(bot, session, user)
        await session.commit()
        return "changed"
