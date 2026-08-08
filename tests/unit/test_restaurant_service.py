from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.handlers.main import restaurant_result_by_code
from app.db.models import Base, FavoriteRestaurant, HousingDailyStatistic, Search, User
from app.restaurants.models import Restaurant
from app.restaurants.service import (
    RestaurantDuplicateError,
    RestaurantLimitError,
    favorites,
    record_daily_statistic,
    remove_favorite,
    save_favorite,
    set_primary,
)


@pytest.mark.asyncio
async def test_restaurant_favorites_limit_duplicates_and_primary_are_user_scoped() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(telegram_user_id=1, telegram_chat_id=1, language="en")
        session.add(user)
        await session.flush()
        first = await save_favorite(session, user, Restaurant(code=1, name="A"))
        await set_primary(session, user, first.id)
        with pytest.raises(RestaurantDuplicateError):
            await save_favorite(session, user, Restaurant(code=1, name="A"))
        for code in range(2, 5):
            await save_favorite(session, user, Restaurant(code=code, name=str(code)))
        with pytest.raises(RestaurantLimitError):
            await save_favorite(session, user, Restaurant(code=5, name="E"))
        saved = await session.get(FavoriteRestaurant, first.id)
        assert saved is not None
        assert saved.name == "A"
    await engine.dispose()


@pytest.mark.asyncio
async def test_restaurant_favorites_persist_multiple_values_and_can_be_removed() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(telegram_user_id=2, telegram_chat_id=2, language="en")
        session.add(user)
        await session.commit()
        user_id = user.id
    async with factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        first = await save_favorite(session, user, Restaurant(code=101, name="First"))
        await save_favorite(session, user, Restaurant(code=202, name="Second"))
        await set_primary(session, user, first.id)
        await session.commit()
    async with factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        saved = await favorites(session, user)
        assert [(item.restaurant_code, item.name) for item in saved] == [
            (101, "First"),
            (202, "Second"),
        ]
        with pytest.raises(RestaurantDuplicateError):
            await save_favorite(session, user, Restaurant(code=101, name="Renamed"))
        assert await remove_favorite(session, user, saved[0].id)
        await session.commit()
    async with factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        assert [(item.restaurant_code, item.name) for item in await favorites(session, user)] == [
            (202, "Second")
        ]
    await engine.dispose()


def test_restaurant_selection_uses_stable_codes_and_rejects_unknown_results() -> None:
    rows = [{"code": 101, "nom": "Translated display name"}]
    assert restaurant_result_by_code(rows, 101) == rows[0]
    assert restaurant_result_by_code(rows, 999) is None
    assert restaurant_result_by_code([{"code": "101"}], 101) is None
    assert restaurant_result_by_code("not a result list", 101) is None


@pytest.mark.asyncio
async def test_daily_statistics_are_immutable_per_search_and_date() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(telegram_user_id=1, telegram_chat_id=1, language="en")
        session.add(user)
        await session.flush()
        search = Search(
            user_id=user.id,
            location_display_name="Paris",
            center_latitude=48.8,
            center_longitude=2.3,
            bounds_west=2.2,
            bounds_north=48.9,
            bounds_east=2.4,
            bounds_south=48.7,
        )
        session.add(search)
        await session.flush()
        day = date(2026, 8, 3)
        assert await record_daily_statistic(session, search, day, 35000, 70000, 5)
        assert await record_daily_statistic(session, search, day, 1, 2, 3) is None
        rows = (await session.scalars(select(HousingDailyStatistic))).all()
        assert [
            (row.cheapest_price_cents, row.highest_price_cents, row.unique_apartment_count)
            for row in rows
        ] == [(35000, 70000, 5)]
    await engine.dispose()
