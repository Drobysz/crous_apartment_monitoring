from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    FavoriteRestaurant,
    HousingDailyStatistic,
    RestaurantMenuDelivery,
    RestaurantSubscription,
    Search,
    User,
)
from app.restaurants.models import Restaurant

PARIS = ZoneInfo("Europe/Paris")
MAX_SAVED_RESTAURANTS = 4


class RestaurantLimitError(ValueError):
    pass


class RestaurantDuplicateError(ValueError):
    pass


class RestaurantNotSavedError(ValueError):
    pass


async def favorites(session: AsyncSession, user: User) -> list[FavoriteRestaurant]:
    return list(
        (
            await session.scalars(
                select(FavoriteRestaurant)
                .where(FavoriteRestaurant.user_id == user.id)
                .order_by(FavoriteRestaurant.name, FavoriteRestaurant.id)
            )
        ).all()
    )


async def save_favorite(
    session: AsyncSession, user: User, restaurant: Restaurant
) -> FavoriteRestaurant:
    existing = await session.scalar(
        select(FavoriteRestaurant).where(
            FavoriteRestaurant.user_id == user.id,
            FavoriteRestaurant.restaurant_code == restaurant.code,
        )
    )
    if existing:
        raise RestaurantDuplicateError
    if len(await favorites(session, user)) >= MAX_SAVED_RESTAURANTS:
        raise RestaurantLimitError
    favorite = FavoriteRestaurant(
        user_id=user.id,
        restaurant_code=restaurant.code,
        name=restaurant.name,
        city=restaurant.city,
        latitude=restaurant.latitude,
        longitude=restaurant.longitude,
        metadata_json=restaurant.metadata,
    )
    session.add(favorite)
    await session.flush()
    return favorite


async def get_subscription(session: AsyncSession, user: User) -> RestaurantSubscription:
    subscription = await session.get(RestaurantSubscription, user.id)
    if subscription is None:
        subscription = RestaurantSubscription(user_id=user.id)
        session.add(subscription)
        await session.flush()
    return subscription


async def set_primary(
    session: AsyncSession, user: User, favorite_id: int
) -> RestaurantSubscription:
    favorite = await session.scalar(
        select(FavoriteRestaurant).where(
            FavoriteRestaurant.id == favorite_id, FavoriteRestaurant.user_id == user.id
        )
    )
    if favorite is None:
        raise RestaurantNotSavedError
    subscription = await get_subscription(session, user)
    subscription.primary_restaurant_id = favorite.id
    return subscription


async def remove_favorite(session: AsyncSession, user: User, favorite_id: int) -> bool:
    favorite = await session.scalar(
        select(FavoriteRestaurant).where(
            FavoriteRestaurant.id == favorite_id, FavoriteRestaurant.user_id == user.id
        )
    )
    if favorite is None:
        return False
    subscription = await get_subscription(session, user)
    if subscription.primary_restaurant_id == favorite.id:
        subscription.primary_restaurant_id = None
    await session.delete(favorite)
    return True


async def due_deliveries(
    session: AsyncSession, now: datetime
) -> list[tuple[User, RestaurantSubscription, FavoriteRestaurant]]:
    local_now = now.astimezone(PARIS)
    rows = (
        await session.execute(
            select(User, RestaurantSubscription, FavoriteRestaurant)
            .join(RestaurantSubscription, RestaurantSubscription.user_id == User.id)
            .join(
                FavoriteRestaurant,
                FavoriteRestaurant.id == RestaurantSubscription.primary_restaurant_id,
            )
            .where(User.is_blocked.is_(False), RestaurantSubscription.delivery_enabled.is_(True))
        )
    ).all()
    result = []
    for user, subscription, favorite in rows:
        scheduled = datetime.combine(local_now.date(), subscription.delivery_time, PARIS)
        if local_now >= scheduled and not await session.scalar(
            select(RestaurantMenuDelivery.id).where(
                RestaurantMenuDelivery.user_id == user.id,
                RestaurantMenuDelivery.delivery_date == local_now.date(),
            )
        ):
            result.append((user, subscription, favorite))
    return result


async def start_delivery(
    session: AsyncSession, user: User, favorite: FavoriteRestaurant, now: datetime
) -> RestaurantMenuDelivery | None:
    local = now.astimezone(PARIS)
    existing = await session.scalar(
        select(RestaurantMenuDelivery).where(
            RestaurantMenuDelivery.user_id == user.id,
            RestaurantMenuDelivery.delivery_date == local.date(),
        )
    )
    if existing:
        return None
    delivery = RestaurantMenuDelivery(
        user_id=user.id,
        favorite_restaurant_id=favorite.id,
        delivery_date=local.date(),
        scheduled_for=now,
    )
    session.add(delivery)
    await session.flush()
    return delivery


async def record_daily_statistic(
    session: AsyncSession,
    search: Search,
    statistic_date: date,
    cheapest_price_cents: int | None,
    highest_price_cents: int | None,
    unique_apartment_count: int,
) -> HousingDailyStatistic | None:
    existing = await session.scalar(
        select(HousingDailyStatistic.id).where(
            HousingDailyStatistic.search_id == search.id,
            HousingDailyStatistic.statistic_date == statistic_date,
        )
    )
    if existing:
        return None
    row = HousingDailyStatistic(
        user_id=search.user_id,
        search_id=search.id,
        search_identifier=f"search:{search.id}",
        cheapest_price_cents=cheapest_price_cents,
        highest_price_cents=highest_price_cents,
        unique_apartment_count=unique_apartment_count,
        statistic_date=statistic_date,
    )
    session.add(row)
    await session.flush()
    return row


def parse_delivery_time(value: str) -> time | None:
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None
