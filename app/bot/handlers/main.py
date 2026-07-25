from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.callbacks import NavCallback
from app.bot.keyboards import back, interval_menu, language_menu, location_menu, radius_menu
from app.bot.navigation.manager import NavigationMessageManager
from app.bot.services import get_or_create_user, latest_search, main_screen
from app.bot.states import LocationFlow
from app.core.i18n import i18n
from app.crous.client import CrousClient
from app.crous.exceptions import CrousUnavailable
from app.crous.models import Bounds
from app.db.models import Search, User
from app.geocoding.base import GeocodingProvider
from app.geocoding.models import GeocodedPlace
from app.notifications.service import apply_snapshot
from app.searches.service import (
    InvalidBounds,
    bounds_from_serialized,
    bounds_log_fields,
    radius_bounds,
    validate_bounds,
)

logger = structlog.get_logger(__name__)


def build_router(session_factory: async_sessionmaker[AsyncSession], geocoder: GeocodingProvider, crous: CrousClient) -> Router:
    router = Router(name="main")
    nav = NavigationMessageManager()
    listing_locks: dict[int, asyncio.Lock] = {}

    async def user_for(message: Message | CallbackQuery, session: AsyncSession) -> User:
        source = message.from_user
        chat_id = message.message.chat.id if isinstance(message, CallbackQuery) and message.message else message.chat.id
        return await get_or_create_user(session, source.id, chat_id, source.language_code)

    async def current(callback: CallbackQuery, data: NavCallback, user: User) -> bool:
        if not callback.message or not nav.is_current_callback(user, callback.message.chat.id, callback.message.message_id, data.version):
            await callback.answer(i18n.text(user.language, "outdated"), show_alert=False)
            return False
        return True

    async def render_location(bot: Bot, session: AsyncSession, user: User) -> None:
        version = user.active_navigation_version + 1
        await nav.render_text_screen(bot, session, user, i18n.text(user.language, "choose-location"), location_menu(user.language, version), "location")

    @router.message(Command("start", "menu"))
    async def start(message: Message, state: FSMContext) -> None:
        async with session_factory() as session:
            user = await user_for(message, session)
            await state.clear()
            await main_screen(message.bot, session, user, nav, force_new=True)
            await session.commit()

    @router.message(Command("language"))
    async def language_command(message: Message) -> None:
        async with session_factory() as session:
            user = await user_for(message, session)
            version = user.active_navigation_version + 1
            await nav.render_text_screen(message.bot, session, user, i18n.text(user.language, "language"), language_menu(user.language, version), "language")
            await session.commit()

    @router.message(Command("range"))
    async def range_command(message: Message) -> None:
        async with session_factory() as session:
            user = await user_for(message, session)
            version = user.active_navigation_version + 1
            await nav.render_text_screen(
                message.bot,
                session,
                user,
                i18n.text(user.language, "set-interval"),
                interval_menu(user.language, version),
                "interval",
            )
            await session.commit()

    @router.message(Command("set_posistion", "set_position"))
    async def set_position_command(message: Message, state: FSMContext) -> None:
        async with session_factory() as session:
            user = await user_for(message, session)
            await state.clear()
            await render_location(message.bot, session, user)
            await session.commit()

    @router.message(Command("available"))
    async def available_command(message: Message) -> None:
        async with session_factory() as session:
            user = await user_for(message, session)
            await send_current_listings_from_message(message, session, user)
            await session.commit()

    @router.message(Command("help", "privacy"))
    async def informational_command(message: Message) -> None:
        async with session_factory() as session:
            user = await user_for(message, session)
            key = "help" if message.text and message.text.startswith("/help") else "privacy"
            version = user.active_navigation_version + 1
            await nav.render_text_screen(message.bot, session, user, i18n.text(user.language, key), back(user.language, version), key)
            await session.commit()

    @router.message(Command("pause", "resume"))
    async def pause_resume(message: Message) -> None:
        async with session_factory() as session:
            user = await user_for(message, session)
            search = await latest_search(session, user)
            if not search:
                await message.answer(i18n.text(user.language, "no-search")); return
            pause = message.text and message.text.startswith("/pause")
            search.is_active = not pause
            if not pause: search.next_check_at = datetime.now(UTC)
            await main_screen(message.bot, session, user, nav)
            await session.commit()

    @router.message(Command("delete_me"))
    async def delete_me(message: Message) -> None:
        async with session_factory() as session:
            user = await user_for(message, session)
            version = user.active_navigation_version + 1
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=i18n.text(user.language, "delete-yes"), callback_data=NavCallback(action="delete-yes", version=version).pack()),
                InlineKeyboardButton(text=i18n.text(user.language, "delete-no"), callback_data=NavCallback(action="menu", version=version).pack()),
            ]])
            await nav.render_text_screen(message.bot, session, user, i18n.text(user.language, "delete-confirm"), keyboard, "delete")
            await session.commit()

    @router.callback_query(NavCallback.filter())
    async def navigation(callback: CallbackQuery, callback_data: NavCallback, state: FSMContext) -> None:
        await callback.answer()
        async with session_factory() as session:
            user = await user_for(callback, session)
            logger.info(
                "navigation_callback_entered",
                callback_query_id=callback.id,
                telegram_user_id=user.telegram_user_id,
                chat_id=user.telegram_chat_id,
                action=callback_data.action,
                navigation_version=callback_data.version,
            )
            if not await current(callback, callback_data, user):
                await session.commit(); return
            action = callback_data.action
            if action == "menu":
                await state.clear(); await main_screen(callback.bot, session, user, nav)
            elif action == "location":
                await state.clear(); await render_location(callback.bot, session, user)
            elif action == "language":
                version = user.active_navigation_version + 1
                await nav.render_text_screen(callback.bot, session, user, i18n.text(user.language, "language"), language_menu(user.language, version), "language")
            elif action == "lang":
                user.language = ("ru", "fr", "ar")[callback_data.entity]
                await main_screen(callback.bot, session, user, nav)
            elif action == "interval":
                version = user.active_navigation_version + 1
                await nav.render_text_screen(callback.bot, session, user, i18n.text(user.language, "set-interval"), interval_menu(user.language, version), "interval")
            elif action == "interval-set":
                search = await latest_search(session, user)
                if search:
                    search.check_interval_minutes = callback_data.entity * 60
                    search.next_check_at = datetime.now(UTC) + timedelta(minutes=search.check_interval_minutes)
                await main_screen(callback.bot, session, user, nav)
            elif action == "city":
                await state.set_state(LocationFlow.city_input)
                version = user.active_navigation_version + 1
                await nav.render_text_screen(callback.bot, session, user, i18n.text(user.language, "enter-city"), back(user.language, version, "location"), "city-input")
            elif action == "place":
                places = (await state.get_data()).get("places", [])
                if callback_data.entity < len(places):
                    await state.update_data(place=places[callback_data.entity])
                    await state.set_state(LocationFlow.radius_selection)
                    version = user.active_navigation_version + 1
                    try:
                        bounds_from_serialized(places[callback_data.entity])
                    except InvalidBounds:
                        include_entire_city = False
                    else:
                        include_entire_city = True
                    await nav.render_text_screen(
                        callback.bot,
                        session,
                        user,
                        i18n.text(user.language, "choose-radius"),
                        radius_menu(user.language, version, include_entire_city=include_entire_city),
                        "radius",
                    )
            elif action == "geo":
                await state.set_state(LocationFlow.geolocation)
                keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=i18n.text(user.language, "send-location"), request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
                await callback.message.answer(i18n.text(user.language, "send-location"), reply_markup=keyboard)  # temporary, allowed only here
            elif action == "radius":
                place = (await state.get_data()).get("place")
                if not place:
                    await render_location(callback.bot, session, user)
                else:
                    try:
                        search = await save_search(session, user, place, callback_data.entity)
                    except InvalidBounds as error:
                        logger.warning(
                            "invalid_bounds_rejected",
                            telegram_user_id=user.telegram_user_id,
                            source="radius_selection",
                            radius_km=callback_data.entity,
                            reason=str(error),
                            raw_bounds={
                                key: place.get(key)
                                for key in ("west", "south", "east", "north")
                            },
                        )
                        await state.clear()
                        await render_location(callback.bot, session, user)
                        await callback.message.answer(i18n.text(user.language, "invalid-location-area"))
                    else:
                        await state.clear()
                        await main_screen(
                            callback.bot,
                            session,
                            user,
                            nav,
                            notice=i18n.text(
                                user.language,
                                "location-saved",
                                value=search.location_display_name,
                            ),
                        )
            elif action == "list":
                await send_current_listings(callback, session, user)
            elif action == "delete-yes":
                await session.delete(user)
                await session.commit()
                await callback.message.edit_text(i18n.text("fr", "deleted"))
                return
            await session.commit()

    @router.message(LocationFlow.city_input)
    async def city_input(message: Message, state: FSMContext) -> None:
        if not message.text or len(message.text) > 200: return
        async with session_factory() as session:
            user = await user_for(message, session)
            try:
                places = await geocoder.search(message.text, user.language)
            except (httpx.HTTPError, InvalidBounds):
                version = user.active_navigation_version + 1
                await nav.render_text_screen(
                    message.bot,
                    session,
                    user,
                    i18n.text(user.language, "error"),
                    back(user.language, version, "location"),
                    "city-input-error",
                )
                await session.commit()
                return
            if not places:
                version = user.active_navigation_version + 1
                await nav.render_text_screen(
                    message.bot,
                    session,
                    user,
                    i18n.text(user.language, "location-not-found"),
                    back(user.language, version, "location"),
                    "city-input-empty",
                )
                await session.commit()
                return
            await present_places(message.bot, session, user, state, places)
            await session.commit()

    @router.message(LocationFlow.geolocation)
    async def geolocation(message: Message, state: FSMContext) -> None:
        if not message.location: return
        async with session_factory() as session:
            user = await user_for(message, session)
            loading_message = await message.answer(
                i18n.text(user.language, "location-searching"),
                reply_markup=ReplyKeyboardRemove(),
            )
            try:
                places = await geocoder.reverse(
                    message.location.latitude,
                    message.location.longitude,
                    user.language,
                )
            except (httpx.HTTPError, InvalidBounds):
                try:
                    await loading_message.delete()
                except TelegramBadRequest:
                    pass
                version = user.active_navigation_version + 1
                await nav.render_text_screen(
                    message.bot,
                    session,
                    user,
                    i18n.text(user.language, "error"),
                    back(user.language, version, "location"),
                    "geolocation-error",
                )
                await session.commit()
                return
            if not places:
                try:
                    await loading_message.delete()
                except TelegramBadRequest:
                    pass
                version = user.active_navigation_version + 1
                await nav.render_text_screen(
                    message.bot,
                    session,
                    user,
                    i18n.text(user.language, "location-not-found"),
                    back(user.language, version, "location"),
                    "geolocation-empty",
                )
                await session.commit()
                return
            try:
                await loading_message.delete()
            except TelegramBadRequest:
                pass
            await present_places(message.bot, session, user, state, places)
            await session.commit()

    async def present_places(bot: Bot, session: AsyncSession, user: User, state: FSMContext, places: list[GeocodedPlace]) -> None:
        await state.update_data(places=[place.__dict__ for place in places])
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        version = user.active_navigation_version + 1
        rows = [[InlineKeyboardButton(text=place.display_name, callback_data=NavCallback(action="place", entity=index, version=version).pack())] for index, place in enumerate(places[:5])]
        rows.append([InlineKeyboardButton(text=i18n.text(user.language, "back"), callback_data=NavCallback(action="location", version=version).pack())])
        await nav.render_text_screen(
            bot,
            session,
            user,
            i18n.text(user.language, "location-search-results"),
            InlineKeyboardMarkup(inline_keyboard=rows),
            "place-selection",
        )
        await state.set_state(LocationFlow.place_selection)

    async def save_search(session: AsyncSession, user: User, raw: dict[str, object], radius: int) -> Search:
        if radius:
            bounds = radius_bounds(float(raw["latitude"]), float(raw["longitude"]), radius)
        else:
            bounds = bounds_from_serialized(raw)
        search = await latest_search(session, user)
        values = {
            "location_display_name": str(raw["display_name"]),
            "city": raw.get("city"),
            "postal_code": raw.get("postal_code"),
            "country_code": raw.get("country_code"),
            "center_latitude": float(raw["latitude"]),
            "center_longitude": float(raw["longitude"]),
            "radius_km": radius or None,
            "bounds_west": bounds.west,
            "bounds_north": bounds.north,
            "bounds_east": bounds.east,
            "bounds_south": bounds.south,
            "next_check_at": datetime.now(UTC),
            "is_active": True,
            "is_initialized": False,
            "consecutive_errors": 0,
        }
        if search is None:
            search = Search(user_id=user.id, **values)
            session.add(search)
        else:
            for field, value in values.items():
                setattr(search, field, value)
        await session.flush()
        return search

    async def send_current_listings(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
        search = await latest_search(session, user)
        if not search:
            await callback.answer(i18n.text(user.language, "no-search"), show_alert=True); return
        lock = listing_locks.setdefault(user.id, asyncio.Lock())
        if lock.locked():
            await callback.answer(i18n.text(user.language, "list-loading"), show_alert=False)
            logger.info(
                "listing_request_deduplicated",
                callback_query_id=callback.id,
                telegram_user_id=user.telegram_user_id,
                search_id=search.id,
            )
            return
        correlation_id = callback.id
        async with lock:
            loading_message = await callback.message.answer(i18n.text(user.language, "list-loading"))
            logger.info(
                "listing_request_started",
                correlation_id=correlation_id,
                telegram_user_id=user.telegram_user_id,
                chat_id=user.telegram_chat_id,
                search_id=search.id,
            )
            try:
                await _send_current_listings(
                    callback.bot,
                    callback.message,
                    session,
                    user,
                    search,
                    correlation_id,
                )
            except (CrousUnavailable, httpx.HTTPError) as error:
                logger.warning(
                    "listing_request_failed",
                    correlation_id=correlation_id,
                    telegram_user_id=user.telegram_user_id,
                    search_id=search.id,
                    reason=str(error),
                )
                await callback.message.answer(i18n.text(user.language, "error"))
            finally:
                try:
                    await loading_message.delete()
                except TelegramBadRequest:
                    pass

    async def send_current_listings_from_message(
        message: Message,
        session: AsyncSession,
        user: User,
    ) -> None:
        search = await latest_search(session, user)
        if not search:
            await message.answer(i18n.text(user.language, "no-search"))
            return
        lock = listing_locks.setdefault(user.id, asyncio.Lock())
        if lock.locked():
            await message.answer(i18n.text(user.language, "list-loading"))
            return
        correlation_id = f"command:{message.message_id}"
        async with lock:
            loading_message = await message.answer(i18n.text(user.language, "list-loading"))
            try:
                await _send_current_listings(
                    message.bot,
                    message,
                    session,
                    user,
                    search,
                    correlation_id,
                )
            except (CrousUnavailable, httpx.HTTPError) as error:
                logger.warning(
                    "listing_request_failed",
                    correlation_id=correlation_id,
                    telegram_user_id=user.telegram_user_id,
                    search_id=search.id,
                    reason=str(error),
                )
                await message.answer(i18n.text(user.language, "error"))
            finally:
                try:
                    await loading_message.delete()
                except TelegramBadRequest:
                    pass

    async def _send_current_listings(
        bot: Bot,
        reply_to: Message,
        session: AsyncSession,
        user: User,
        search: Search,
        correlation_id: str,
    ) -> None:
        try:
            bounds = validate_bounds(
                Bounds(search.bounds_west, search.bounds_north, search.bounds_east, search.bounds_south)
            )
        except InvalidBounds as error:
            logger.warning(
                "invalid_persisted_search_bounds",
                telegram_user_id=user.telegram_user_id,
                search_id=search.id,
                reason=str(error),
                **bounds_log_fields(
                    Bounds(search.bounds_west, search.bounds_north, search.bounds_east, search.bounds_south)
                ),
            )
            await reply_to.answer(i18n.text(user.language, "invalid-location-area"))
            return
        listings = await crous.search(bounds, correlation_id=correlation_id)
        # Persist the exact snapshot before delivery so worker, database, and
        # the first button press all observe the same search-scoped set.
        await apply_snapshot(session, search, listings)
        await session.commit()
        logger.info(
            "listing_snapshot_committed",
            correlation_id=correlation_id,
            telegram_user_id=user.telegram_user_id,
            search_id=search.id,
            listing_count=len(listings),
        )
        if not listings:
            await reply_to.answer(i18n.text(user.language, "no-listings"))
            await main_screen(bot, session, user, nav)
            return
        from app.bot.cards import send_accommodation_card
        for listing in listings[:5]:
            try:
                sent_message_id = await send_accommodation_card(
                    bot,
                    user.telegram_chat_id,
                    listing,
                    user.language,
                    datetime.now(UTC),
                )
            except Exception as error:
                logger.exception(
                    "listing_card_send_failed",
                    correlation_id=correlation_id,
                    telegram_user_id=user.telegram_user_id,
                    search_id=search.id,
                    external_listing_id=listing.external_id,
                    reason=str(error),
                )
                continue
            logger.info(
                "listing_card_sent",
                correlation_id=correlation_id,
                telegram_user_id=user.telegram_user_id,
                search_id=search.id,
                external_listing_id=listing.external_id,
                telegram_message_id=sent_message_id,
            )
        await main_screen(bot, session, user, nav)
        logger.info(
            "listing_request_completed",
            correlation_id=correlation_id,
            telegram_user_id=user.telegram_user_id,
            search_id=search.id,
            rendered_count=min(len(listings), 5),
        )

    return router
