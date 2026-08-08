from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, Search, User
from app.monitoring.service import get_active_searches
from app.restaurants.models import Restaurant
from app.restaurants.service import (
    due_deliveries,
    get_subscription,
    save_favorite,
    set_primary,
)


def make_search(user_id: int) -> Search:
    return Search(
        user_id=user_id,
        location_display_name="Nancy",
        center_latitude=48.69,
        center_longitude=6.18,
        bounds_west=6.1,
        bounds_north=48.8,
        bounds_east=6.3,
        bounds_south=48.6,
    )


@pytest.mark.asyncio
async def test_housing_monitoring_isolated_by_search_and_user() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        first = User(telegram_user_id=101, telegram_chat_id=101, language="en")
        second = User(telegram_user_id=202, telegram_chat_id=202, language="en")
        session.add_all((first, second))
        await session.flush()
        first_search, second_search = make_search(first.id), make_search(second.id)
        first_search.is_active = False
        second_search.is_active = True
        session.add_all((first_search, second_search))
        await session.commit()

    async with factory() as session:
        active = await get_active_searches(session)
        assert [(search.user_id, user.telegram_user_id) for search, user in active] == [
            (second.id, 202)
        ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_canteen_delivery_isolated_and_independent_from_housing_monitoring() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        first = User(telegram_user_id=301, telegram_chat_id=301, language="en")
        second = User(telegram_user_id=302, telegram_chat_id=302, language="en")
        session.add_all((first, second))
        await session.flush()
        first_search, second_search = make_search(first.id), make_search(second.id)
        first_search.is_active = True
        second_search.is_active = False
        session.add_all((first_search, second_search))

        first_favorite = await save_favorite(session, first, Restaurant(code=301, name="First"))
        second_favorite = await save_favorite(session, second, Restaurant(code=302, name="Second"))
        await set_primary(session, first, first_favorite.id)
        await set_primary(session, second, second_favorite.id)
        first_subscription = await get_subscription(session, first)
        second_subscription = await get_subscription(session, second)
        first_subscription.delivery_enabled = False
        second_subscription.delivery_enabled = True
        first_subscription.delivery_time = second_subscription.delivery_time = time(8)
        await session.commit()

    now = datetime(2026, 8, 8, 9, tzinfo=ZoneInfo("Europe/Paris")).astimezone(UTC)
    async with factory() as session:
        due = await due_deliveries(session, now)
        assert [(user.id, favorite.restaurant_code) for user, _, favorite in due] == [
            (second.id, 302)
        ]
        active_housing = await get_active_searches(session)
        assert [(search.user_id, user.telegram_user_id) for search, user in active_housing] == [
            (first.id, 301)
        ]
    await engine.dispose()
