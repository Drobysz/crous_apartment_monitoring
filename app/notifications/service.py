from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crous.models import CrousListing
from app.db.models import Listing, Search, SearchListing


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


async def apply_snapshot(session: AsyncSession, search: Search, items: list[CrousListing]) -> None:
    """Persist one fully verified search-scoped availability snapshot."""
    now = datetime.now(UTC)
    prior = {row.listing_id: row for row in (await session.scalars(select(SearchListing).where(SearchListing.search_id == search.id))).all()}
    current_ids: set[int] = set()
    for item in items:
        listing = await upsert_listing(session, item)
        current_ids.add(listing.id)
        link = prior.get(listing.id)
        if link is None:
            session.add(SearchListing(search_id=search.id, listing_id=listing.id, is_currently_available=True, first_seen_at=now, last_seen_at=now))
        elif not link.is_currently_available:
            link.is_currently_available, link.reappeared_at, link.last_seen_at = True, now, now
        else:
            link.last_seen_at = now
    for listing_id, link in prior.items():
        if listing_id not in current_ids and link.is_currently_available:
            link.is_currently_available, link.disappeared_at = False, now
