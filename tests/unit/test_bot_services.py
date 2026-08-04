from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.keyboards import main_menu
from app.bot.navigation.manager import NavigationMessageManager
from app.bot.services import available_listing_count, format_last_check
from app.core.i18n import i18n
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


def test_last_check_is_rendered_in_the_configured_paris_timezone() -> None:
    assert format_last_check(datetime(2026, 7, 25, 17, 32, tzinfo=UTC)) == "25/07 19:32"


def test_main_menu_has_no_per_user_monitoring_interval() -> None:
    actions = [button.callback_data for row in main_menu("ru", 1).inline_keyboard for button in row]
    assert all(action is None or "interval" not in action for action in actions)
    assert {"housing", "restaurant", "subscription", "language"} == {
        action.split(":")[1] for action in actions if action
    }


def test_localized_escaped_newlines_render_as_real_line_breaks() -> None:
    text = i18n.text("en", "plan-detail", plan="Season", price="€10", validity="July to October")
    assert "\\n" not in text
    assert "\n" in text


def test_main_menu_uses_a_housing_submenu() -> None:
    callbacks = {button.callback_data for row in main_menu("en", 4, monitoring_enabled=True).inline_keyboard for button in row}
    assert any(callback and ":housing:" in callback for callback in callbacks)
    assert not any(callback and "monitor-toggle" in callback for callback in callbacks)


def test_test_subscription_reset_button_is_opt_in() -> None:
    regular = [button.callback_data for row in main_menu("en", 1).inline_keyboard for button in row]
    developer = [
        button.callback_data
        for row in main_menu("en", 1, show_test_reset=True).inline_keyboard
        for button in row
    ]
    assert not any(action and ":test-reset:" in action for action in regular)
    assert any(action and ":test-reset:" in action for action in developer)


@pytest.mark.asyncio
async def test_navigation_replaces_the_previous_message_at_the_end_of_chat() -> None:
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    class FakeBot:
        async def delete_message(self, *args: object, **kwargs: object) -> bool:
            calls.append(("delete", args, kwargs))
            return True

        async def send_message(self, *args: object, **kwargs: object) -> SimpleNamespace:
            calls.append(("send", args, kwargs))
            return SimpleNamespace(chat=SimpleNamespace(id=99), message_id=100)

    class FakeSession:
        async def flush(self) -> None:
            return None

    user = User(
        telegram_user_id=1,
        telegram_chat_id=99,
        language="ru",
        active_navigation_chat_id=99,
        active_navigation_message_id=10,
        active_navigation_version=4,
    )
    await NavigationMessageManager().render_text_screen(
        FakeBot(),  # type: ignore[arg-type]
        FakeSession(),  # type: ignore[arg-type]
        user,
        "Updated navigation",
        InlineKeyboardMarkup(inline_keyboard=[]),
        "main",
    )

    assert [call[0] for call in calls] == ["delete", "send"]
    assert user.active_navigation_message_id == 100
    assert user.active_navigation_version == 5
