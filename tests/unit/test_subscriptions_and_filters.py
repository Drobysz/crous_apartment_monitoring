from datetime import UTC, datetime
from urllib.parse import parse_qs

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.crous.models import CrousListing
from app.db.models import Base, Purchase, Search, SubscriptionPlan, User, UserSubscription
from app.payments import stripe
from app.payments.stripe import (
    create_checkout_session,
    process_paid_checkout,
    valid_payment_return_token,
)
from app.searches.filters import (
    FilterValidationError,
    listing_matches_filters,
    parse_price_range,
    parse_surface_range,
)
from app.subscriptions.service import (
    activate_subscription,
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
        user_id=1,
        location_display_name="Nancy",
        center_latitude=48.69,
        center_longitude=6.18,
        bounds_west=6.1,
        bounds_north=48.8,
        bounds_east=6.3,
        bounds_south=48.6,
        price_min_cents=30_000,
        price_max_cents=65_000,
        surface_min_m2=15,
        surface_max_m2=35,
        accommodation_format="individuel",
    )
    assert listing_matches_filters(
        CrousListing(
            "1",
            "https://example.test/1",
            "Studio",
            price_cents=40_000,
            surface_min=20,
            surface_max=20,
            occupancy_type="Individuel",
        ),
        search,
    )
    assert not listing_matches_filters(
        CrousListing("2", "https://example.test/2", "Unknown"), search
    )


def test_filter_bounds_are_inclusive_and_support_a_single_bound() -> None:
    assert parse_price_range("≥300,50") == (30_050, None)
    assert parse_price_range("≤650.25") == (None, 65_025)
    assert parse_surface_range("≥15,5") == (15.5, None)
    assert parse_surface_range("max 35.25 m²") == (None, 35.25)
    search = Search(
        user_id=1,
        location_display_name="Nancy",
        center_latitude=48.69,
        center_longitude=6.18,
        bounds_west=6.1,
        bounds_north=48.8,
        bounds_east=6.3,
        bounds_south=48.6,
        price_min_cents=30_000,
        price_max_cents=30_000,
        surface_min_m2=20,
        surface_max_m2=20,
    )
    assert listing_matches_filters(
        CrousListing(
            "boundary",
            "https://example.test/boundary",
            "Studio",
            price_cents=30_000,
            surface_min=20,
            surface_max=20,
        ),
        search,
    )


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("-1", "negative"),
        ("650-300", "min-greater"),
        ("300.001", "precision"),
        ("invalid", "format"),
    ],
)
def test_price_range_validation_reports_stable_localization_codes(value: str, code: str) -> None:
    with pytest.raises(FilterValidationError) as error:
        parse_price_range(value)
    assert error.value.code == code


def test_legacy_accommodation_format_remains_compatible() -> None:
    search = Search(
        user_id=1,
        location_display_name="Nancy",
        center_latitude=48.69,
        center_longitude=6.18,
        bounds_west=6.1,
        bounds_north=48.8,
        bounds_east=6.3,
        bounds_south=48.6,
        accommodation_format="individuel",
    )
    individual = CrousListing(
        "individual", "https://example.test/individual", "Studio", occupancy_type="Individuel"
    )
    colocation = CrousListing(
        "colocation", "https://example.test/colocation", "Room", occupancy_type="Colocation"
    )
    assert listing_matches_filters(individual, search)
    assert not listing_matches_filters(colocation, search)
    search.accommodation_format = "colocation"
    assert not listing_matches_filters(individual, search)
    assert listing_matches_filters(colocation, search)


def test_season_purchase_after_end_targets_next_year() -> None:
    plan = SubscriptionPlan(code="season", name="Season", price_cents=1000)
    starts, ends = entitlement_dates(plan, datetime(2026, 11, 1, tzinfo=UTC), Settings())
    assert starts == datetime(2027, 7, 7, tzinfo=UTC)
    assert ends == datetime(2027, 10, 31, 23, 59, 59, 999999, tzinfo=UTC)


@pytest.mark.asyncio
async def test_trial_is_available_once_for_exactly_twelve_hours_and_survives_restart() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(telegram_user_id=10, telegram_chat_id=10, language="en")
        session.add(user)
        await session.flush()
        started = datetime(2026, 7, 10, 23, 30, tzinfo=UTC)
        first = await activate_trial(session, user, started)
        assert first is not None
        assert first.starts_at == started
        assert first.ends_at == datetime(2026, 7, 11, 11, 30, tzinfo=UTC)
        assert await activate_trial(session, user) is None
        assert (
            await get_effective_subscription(
                session, user, datetime(2026, 7, 11, 11, 29, 59, tzinfo=UTC)
            )
        ).plan.code == "trial"
        assert (
            await get_effective_subscription(
                session, user, datetime(2026, 7, 11, 11, 30, tzinfo=UTC)
            )
        ).plan.code == "free"
        assert await plan_by_code(session, "season") is not None
        await session.commit()
        user_id = user.id
    async with factory() as session:
        restarted_user = await session.get(User, user_id)
        assert restarted_user is not None
        assert restarted_user.trial_used_at == started.replace(tzinfo=None)
        assert (
            await activate_trial(session, restarted_user, datetime(2026, 7, 12, tzinfo=UTC)) is None
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_an_in_season_purchase_supersedes_an_active_trial() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(telegram_user_id=14, telegram_chat_id=14, language="en")
        trial_plan = SubscriptionPlan(code="trial", name="Trial", price_cents=0, is_active=False)
        season_plan = SubscriptionPlan(code="season", name="Season", price_cents=1000)
        session.add_all((user, trial_plan, season_plan))
        await session.flush()
        trial_started = datetime(2026, 7, 29, 20, tzinfo=UTC)
        await activate_subscription(session, user, trial_plan, source="trial", now=trial_started)
        purchased_at = datetime(2026, 7, 30, 0, 30, tzinfo=UTC)
        await activate_subscription(session, user, season_plan, source="stripe", now=purchased_at)

        assert (await get_effective_subscription(session, user, purchased_at)).plan.code == "season"
        statuses = [
            subscription.status
            for subscription in (await session.scalars(select(UserSubscription))).all()
        ]
        assert statuses == ["superseded", "active"]
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
async def test_checkout_uses_database_price_data_without_a_predefined_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        settings = Settings(
            stripe_secret_key="sk_test_example", public_base_url="https://bot.example.test"
        )
        assert (
            await create_checkout_session(session, user, "season", settings)
            == "https://checkout.stripe.test/session"
        )
    assert parse_qs(requests[0].decode())["line_items[0][price_data][unit_amount]"] == ["1337"]
    assert "line_items[0][price]" not in parse_qs(requests[0].decode())
    await engine.dispose()


@pytest.mark.asyncio
async def test_verified_checkout_session_activates_once_before_webhook_arrives() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(telegram_user_id=13, telegram_chat_id=13, language="en")
        plan = SubscriptionPlan(code="season", name="Season", price_cents=1000)
        session.add_all((user, plan))
        await session.flush()
        checkout = {
            "id": "cs_test_verified",
            "payment_status": "paid",
            "amount_total": 1000,
            "currency": "eur",
            "client_reference_id": str(user.id),
            "metadata": {
                "internal_user_id": str(user.id),
                "telegram_user_id": str(user.telegram_user_id),
                "subscription_id": str(plan.id),
                "plan_code": "season",
            },
        }
        settings = Settings(stripe_secret_key="sk_test_example")
        payment = await process_paid_checkout(session, checkout, settings)
        assert payment is not None and not payment.duplicate
        await session.flush()
        duplicate = await process_paid_checkout(session, checkout, settings, event_id="evt_later")
        assert duplicate is not None and duplicate.duplicate
        assert len((await session.scalars(select(Purchase))).all()) == 1
        assert len((await session.scalars(select(UserSubscription))).all()) == 1
    await engine.dispose()


def test_cancel_return_token_is_bound_to_the_checkout_user_and_plan() -> None:
    settings = Settings(stripe_secret_key="sk_test_example")
    token = stripe.payment_return_token(settings, 7, 3)
    assert valid_payment_return_token(settings, 7, 3, token)
    assert not valid_payment_return_token(settings, 8, 3, token)
