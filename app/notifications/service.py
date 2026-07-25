from __future__ import annotations

from datetime import UTC, datetime

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.cards import send_accommodation_card
from app.crous.models import CrousListing
from app.db.models import Listing, Notification, Search, SearchListing, User


async def upsert_listing(session: AsyncSession, item: CrousListing) -> Listing:
    listing = await session.scalar(select(Listing).where(Listing.source == "crous", Listing.external_id == item.external_id))
    fields = {key: value for key, value in item.__dict__.items() if key in Listing.__table__.columns}
    if listing is None:
        listing = Listing(source="crous", **fields)
        session.add(listing)
        await session.flush()
    else:
        for key, value in fields.items(): setattr(listing, key, value)
        listing.last_seen_at = datetime.now(UTC)
    return listing


async def apply_snapshot(session: AsyncSession, search: Search, items: list[CrousListing]) -> list[tuple[Listing, str]]:
    """Persist snapshot and return notification-worthy changes after baseline only."""
    now = datetime.now(UTC)
    prior = {row.listing_id: row for row in (await session.scalars(select(SearchListing).where(SearchListing.search_id == search.id))).all()}
    current_ids: set[int] = set()
    changes: list[tuple[Listing, str]] = []
    for item in items:
        listing = await upsert_listing(session, item)
        current_ids.add(listing.id)
        link = prior.get(listing.id)
        if link is None:
            session.add(SearchListing(search_id=search.id, listing_id=listing.id, is_currently_available=True, first_seen_at=now, last_seen_at=now))
            if search.is_initialized: changes.append((listing, "new"))
        elif not link.is_currently_available:
            link.is_currently_available, link.reappeared_at, link.last_seen_at = True, now, now
            if search.is_initialized: changes.append((listing, "reappeared"))
        else:
            link.last_seen_at = now
    for listing_id, link in prior.items():
        if listing_id not in current_ids and link.is_currently_available:
            link.is_currently_available, link.disappeared_at = False, now
    search.is_initialized, search.last_checked_at, search.last_success_at, search.consecutive_errors = True, now, now, 0
    return changes


async def send_change(bot: Bot, session: AsyncSession, user: User, search: Search, listing: Listing, kind: str) -> None:
    notification = Notification(user_id=user.id, search_id=search.id, listing_id=listing.id, notification_type=kind)
    session.add(notification); await session.flush()
    item = CrousListing(**{field: getattr(listing, field) for field in CrousListing.__dataclass_fields__ if hasattr(listing, field)})
    try:
        notification.telegram_message_id = await send_accommodation_card(bot, user.telegram_chat_id, item, user.language, listing.first_seen_at, available_again=kind == "reappeared")
        notification.status, notification.sent_at = "sent", datetime.now(UTC)
    except Exception as error:
        notification.status, notification.error = "failed", str(error)[:1000]
