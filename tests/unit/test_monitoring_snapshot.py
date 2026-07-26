from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.crous.models import CrousListing
from app.db.models import (
    Base,
    Listing,
    Search,
    SearchDisplayGroup,
    SearchDisplayMessage,
    SearchListing,
    User,
)
from app.monitoring.service import SnapshotDeliveryError, synchronize_search
from app.monitoring.snapshot import canonical_snapshot


def listing(identifier: str, *, price: int = 500) -> CrousListing:
    return CrousListing(
        external_id=identifier,
        canonical_url=f"https://crous.example/tools/1/accommodations/{identifier}?tracking=ignored",
        title=f"Studio {identifier}",
        address="1 Rue de Test",
        price_cents=price,
        price_original=f"{price / 100:.2f} €",
        surface_original="18 m²",
    )


def test_snapshot_is_order_independent_and_ignores_image_cache() -> None:
    first = listing("one")
    second = listing("two")
    _, fingerprint = canonical_snapshot([first, second, first])
    first.primary_image_url = "https://images.example/cache-busted.jpg"
    _, reordered = canonical_snapshot([second, first])
    assert fingerprint == reordered


@pytest.mark.asyncio
async def test_changed_snapshot_replaces_only_its_own_message_group() -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.sent: list[int] = []
            self.deleted: list[int] = []

        async def send_message(self, _chat_id: int, *_: object, **__: object) -> SimpleNamespace:
            message_id = len(self.sent) + 1
            self.sent.append(message_id)
            return SimpleNamespace(message_id=message_id)

        async def delete_message(self, _chat_id: int, message_id: int) -> bool:
            self.deleted.append(message_id)
            return True

    class FakeCrous:
        def __init__(self, items: list[CrousListing]) -> None:
            self.items = items

        async def search(self, *_: object, **__: object) -> list[CrousListing]:
            return self.items

    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(telegram_user_id=1, telegram_chat_id=42, language="ru")
        session.add(user)
        await session.flush()
        search = Search(
            user_id=user.id,
            location_display_name="Nancy",
            center_latitude=48.69,
            center_longitude=6.18,
            bounds_west=6.1,
            bounds_north=48.8,
            bounds_east=6.3,
            bounds_south=48.6,
        )
        session.add(search)
        await session.commit()
        search_id = search.id

    bot = FakeBot()
    crous = FakeCrous([listing("one"), listing("two")])
    assert await synchronize_search(factory, bot, crous, search_id) == "changed"  # type: ignore[arg-type]
    assert await synchronize_search(factory, bot, crous, search_id) == "unchanged"  # type: ignore[arg-type]
    assert bot.sent == [1, 2]

    crous.items = [listing("one", price=501), listing("three")]
    assert await synchronize_search(factory, bot, crous, search_id) == "changed"  # type: ignore[arg-type]
    assert bot.sent == [1, 2, 3, 4]
    assert bot.deleted == [1, 2]
    async with factory() as session:
        active = (await session.scalars(select(SearchDisplayGroup).where(SearchDisplayGroup.status == "active"))).all()
        messages = (await session.scalars(select(SearchDisplayMessage))).all()
        assert len(active) == 1
        assert active[0].listing_count == 2
        assert {message.telegram_message_id for message in messages} == {3, 4}
        removed_listing = await session.scalar(select(Listing).where(Listing.external_id == "two"))
        assert removed_listing is not None
        removed_link = await session.get(SearchListing, (search_id, removed_listing.id))
        assert removed_link is not None
        assert not removed_link.is_currently_available
        assert removed_link.disappeared_at is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_delivery_failure_keeps_previous_active_group() -> None:
    class FailingBot:
        def __init__(self) -> None:
            self.next_id = 1
            self.fail = False
            self.deleted: list[int] = []

        async def send_message(self, _chat_id: int, *_: object, **__: object) -> SimpleNamespace:
            if self.fail:
                raise RuntimeError("Telegram unavailable")
            result = SimpleNamespace(message_id=self.next_id)
            self.next_id += 1
            return result

        async def delete_message(self, _chat_id: int, message_id: int) -> bool:
            self.deleted.append(message_id)
            return True

    class FakeCrous:
        items = [listing("one")]

        async def search(self, *_: object, **__: object) -> list[CrousListing]:
            return self.items

    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(telegram_user_id=2, telegram_chat_id=43, language="ru")
        session.add(user)
        await session.flush()
        search = Search(user_id=user.id, location_display_name="Nancy", center_latitude=48.69, center_longitude=6.18, bounds_west=6.1, bounds_north=48.8, bounds_east=6.3, bounds_south=48.6)
        session.add(search)
        await session.commit()
        search_id = search.id
    bot, crous = FailingBot(), FakeCrous()
    await synchronize_search(factory, bot, crous, search_id)  # type: ignore[arg-type]
    bot.fail = True
    crous.items = [listing("two")]
    with pytest.raises(SnapshotDeliveryError):
        await synchronize_search(factory, bot, crous, search_id)  # type: ignore[arg-type]
    async with factory() as session:
        active = (await session.scalars(select(SearchDisplayGroup).where(SearchDisplayGroup.status == "active"))).all()
        assert len(active) == 1
        assert active[0].fingerprint != canonical_snapshot(crous.items)[1]
    await engine.dispose()
