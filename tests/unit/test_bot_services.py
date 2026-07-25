from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.services import available_listing_count
from app.db.models import Base, Listing, Search, SearchListing, User


@pytest.mark.asyncio
async def test_available_listing_count_is_scoped_to_the_current_search() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(telegram_user_id=1, telegram_chat_id=1, language="ru")
        session.add(user)
        await session.flush()
        search = Search(
            user_id=user.id,
            location_display_name="Nancy (54000)",
            center_latitude=48.69,
            center_longitude=6.18,
            bounds_west=6.1,
            bounds_north=48.8,
            bounds_east=6.3,
            bounds_south=48.6,
        )
        another_search = Search(
            user_id=user.id,
            location_display_name="Besancon (25000)",
            center_latitude=47.24,
            center_longitude=6.02,
            bounds_west=5.9,
            bounds_north=47.4,
            bounds_east=6.1,
            bounds_south=47.1,
        )
        session.add_all((search, another_search))
        await session.flush()
        listings = [
            Listing(
                source="crous",
                external_id=f"listing-{index}",
                canonical_url=f"https://example.test/{index}",
                title="Test listing",
                raw_payload={},
            )
            for index in range(3)
        ]
        session.add_all(listings)
        await session.flush()
        now = datetime.now(UTC)
        session.add_all(
            (
                SearchListing(search_id=search.id, listing_id=listings[0].id, is_currently_available=True, first_seen_at=now, last_seen_at=now),
                SearchListing(search_id=search.id, listing_id=listings[1].id, is_currently_available=True, first_seen_at=now, last_seen_at=now),
                SearchListing(search_id=search.id, listing_id=listings[2].id, is_currently_available=False, first_seen_at=now, last_seen_at=now),
                SearchListing(search_id=another_search.id, listing_id=listings[2].id, is_currently_available=True, first_seen_at=now, last_seen_at=now),
            )
        )
        await session.commit()

        assert await available_listing_count(session, search) == 2
        assert await available_listing_count(session, another_search) == 1
        assert await available_listing_count(session, None) == 0

    await engine.dispose()
