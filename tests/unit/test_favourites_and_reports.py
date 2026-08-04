from __future__ import annotations

import pytest
from sqlalchemy import BigInteger, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    Base,
    FavoriteTransitionEvent,
    Listing,
    RestaurantMenuDelivery,
    Search,
    User,
)
from app.discord_bot.adapter import listing_embed_payload
from app.favourites.service import (
    add_favorite,
    favorites,
    record_completed_snapshot_transitions,
    remove_favorite,
)
from app.reports.service import ReportValidationError, create_report, user_reports


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as value:
        yield value
    await engine.dispose()


async def _fixture_data(session: AsyncSession) -> tuple[User, Search, Listing]:
    user = User(telegram_user_id=10, telegram_chat_id=11, language="en")
    session.add(user)
    await session.flush()
    search = Search(
        user_id=user.id,
        location_display_name="Nancy",
        center_latitude=48.69,
        center_longitude=6.1,
        bounds_west=6.0,
        bounds_north=48.8,
        bounds_east=6.2,
        bounds_south=48.5,
    )
    listing = Listing(
        source="crous",
        external_id="stable-id",
        canonical_url="https://example.test/listing",
        title="Studio",
        raw_payload={},
    )
    session.add_all((search, listing))
    await session.flush()
    return user, search, listing


@pytest.mark.asyncio
async def test_favourite_add_remove_is_idempotent_and_scoped(session: AsyncSession) -> None:
    user, _, listing = await _fixture_data(session)
    other = User(telegram_user_id=12, telegram_chat_id=13, language="en")
    session.add(other)
    await session.flush()

    assert await add_favorite(session, user, listing.id)
    assert await add_favorite(session, user, listing.id)
    assert [item.id for item in await favorites(session, user)] == [listing.id]
    assert await remove_favorite(session, other, listing.id)
    assert [item.id for item in await favorites(session, user)] == [listing.id]
    assert await remove_favorite(session, user, listing.id)
    assert await remove_favorite(session, user, listing.id)
    assert await favorites(session, user) == []


@pytest.mark.asyncio
async def test_completed_snapshot_transitions_are_baselined_and_deduplicated(
    session: AsyncSession,
) -> None:
    user, search, listing = await _fixture_data(session)
    await add_favorite(session, user, listing.id)
    # First complete observation is the baseline, whether present or absent.
    assert await record_completed_snapshot_transitions(session, search, {listing.id}) == []
    await session.flush()
    appeared = await record_completed_snapshot_transitions(session, search, set())
    assert [event.transition for event in appeared] == ["disappeared"]
    assert await record_completed_snapshot_transitions(session, search, set()) == []
    reappeared = await record_completed_snapshot_transitions(session, search, {listing.id})
    assert [event.transition for event in reappeared] == ["appeared"]
    assert await record_completed_snapshot_transitions(session, search, {listing.id}) == []
    assert len((await session.scalars(select(FavoriteTransitionEvent))).all()) == 2


@pytest.mark.asyncio
async def test_reports_are_validated_and_visible_only_to_the_owner(session: AsyncSession) -> None:
    user, _, _ = await _fixture_data(session)
    other = User(telegram_user_id=12, telegram_chat_id=13, language="en")
    session.add(other)
    await session.flush()
    with pytest.raises(ReportValidationError):
        await create_report(session, user, "   ", None)
    report = await create_report(session, user, "A complete report", None)
    assert report.text == "A complete report"
    assert [item.text for item in await user_reports(session, user)] == ["A complete report"]
    assert await user_reports(session, other) == []


def test_discord_embed_payload_limits_content() -> None:
    payload = listing_embed_payload(
        type(
            "ListingView",
            (),
            {
                "title": "A" * 300,
                "canonical_url": "https://example.test/listing",
                "price_original": "500 €",
                "surface_original": "20 m²",
                "address": "B" * 5000,
                "primary_image_url": None,
            },
        )(),
        "en",
    )
    assert len(str(payload["title"])) == 256
    assert len(str(payload["description"])) == 4096


def test_restaurant_delivery_telegram_message_metadata_is_bigint() -> None:
    assert isinstance(RestaurantMenuDelivery.__table__.c.telegram_message_id.type, BigInteger)
