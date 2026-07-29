from datetime import UTC, datetime
from urllib.parse import parse_qs

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.crous.models import CrousListing
from app.db.models import Base, Search, SubscriptionPlan, User
from app.payments import stripe
from app.payments.stripe import create_checkout_session
from app.searches.filters import listing_matches_filters, parse_price_range, parse_surface_range
from app.subscriptions.service import (
    activate_trial,
    entitlement_dates,
    get_effective_subscription,
    plan_by_code,
    reset_current_subscription,
)


def test_filter_ranges_and_missing_listing_data_policy() -> None:
    assert parse_price_range("300 — 650") == (30_000, 65_000)
    assert parse_surface_range("15 m² - 35 m²") == (15.0, 35.0)
    search = Search(
        user_id=1, location_display_name="Nancy", center_latitude=48.69, center_longitude=6.18,
        bounds_west=6.1, bounds_north=48.8, bounds_east=6.3, bounds_south=48.6,
        price_min_cents=30_000, price_max_cents=65_000, surface_min_m2=15, surface_max_m2=35,
        accommodation_format="individuel",
    )
    assert listing_matches_filters(CrousListing("1", "https://example.test/1", "Studio", price_cents=40_000, surface_min=20, surface_max=20, occupancy_type="Individuel"), search)
    assert not listing_matches_filters(CrousListing("2", "https://example.test/2", "Unknown"), search)


def test_season_purchase_after_end_targets_next_year() -> None:
    plan = SubscriptionPlan(code="season", name="Season", price_cents=1000)
    starts, ends = entitlement_dates(plan, datetime(2026, 11, 1, tzinfo=UTC), Settings())
    assert starts == datetime(2027, 7, 7, tzinfo=UTC)
    assert ends == datetime(2027, 10, 31, 23, 59, 59, 999999, tzinfo=UTC)


@pytest.mark.asyncio
async def test_trial_is_available_once_and_falls_back_to_free() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(telegram_user_id=10, telegram_chat_id=10, language="en")
        session.add(user)
        await session.flush()
        first = await activate_trial(session, user, datetime(2026, 7, 10, tzinfo=UTC))
        assert first is not None
        assert await activate_trial(session, user) is None
        assert (await get_effective_subscription(session, user, datetime(2026, 7, 10, 1, tzinfo=UTC))).plan.code == "trial"
        assert (await get_effective_subscription(session, user, datetime(2026, 7, 11, tzinfo=UTC))).plan.code == "free"
        assert await plan_by_code(session, "season") is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_test_reset_revokes_entitlement_but_does_not_remove_purchases() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(telegram_user_id=11, telegram_chat_id=11, language="en")
        session.add(user)
        await session.flush()
        now = datetime.now(UTC)
        await activate_trial(session, user, now)
        assert await reset_current_subscription(session, user)
        assert (await get_effective_subscription(session, user, now)).plan.code == "free"
    await engine.dispose()


@pytest.mark.asyncio
async def test_checkout_uses_database_price_data_without_a_predefined_product(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[bytes] = []

    class FakeResponse:
        is_success = True

        def json(self) -> dict[str, str]:
            return {"url": "https://checkout.stripe.test/session"}

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, _: str, *, content: str, **__: object) -> FakeResponse:
            requests.append(content.encode())
            return FakeResponse()

    monkeypatch.setattr(stripe.httpx, "AsyncClient", lambda **_: FakeClient())
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(telegram_user_id=12, telegram_chat_id=12, language="en")
        plan = SubscriptionPlan(code="season", name="Season", price_cents=1337)
        session.add_all((user, plan))
        await session.flush()
        settings = Settings(stripe_secret_key="sk_test_example", public_base_url="https://bot.example.test")
        assert await create_checkout_session(session, user, "season", settings) == "https://checkout.stripe.test/session"
    assert parse_qs(requests[0].decode())["line_items[0][price_data][unit_amount]"] == ["1337"]
    assert "line_items[0][price]" not in parse_qs(requests[0].decode())
    await engine.dispose()
