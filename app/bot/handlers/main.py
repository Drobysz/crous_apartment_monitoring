from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import Bot, Router
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
from app.crous.models import Bounds
from app.db.models import Search, User
from app.geocoding.base import GeocodingProvider
from app.geocoding.models import GeocodedPlace
from app.searches.service import radius_bounds, validate_bounds


def build_router(session_factory: async_sessionmaker[AsyncSession], geocoder: GeocodingProvider, crous: CrousClient) -> Router:
    router = Router(name="main")
    nav = NavigationMessageManager()

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
    async def start(message: Message) -> None:
        async with session_factory() as session:
            user = await user_for(message, session)
            await main_screen(message.bot, session, user, nav)
            await session.commit()

    @router.message(Command("language"))
    async def language_command(message: Message) -> None:
        async with session_factory() as session:
            user = await user_for(message, session)
            version = user.active_navigation_version + 1
            await nav.render_text_screen(message.bot, session, user, i18n.text(user.language, "language"), language_menu(user.language, version), "language")
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
                    await nav.render_text_screen(callback.bot, session, user, i18n.text(user.language, "choose-radius"), radius_menu(user.language, version), "radius")
            elif action == "geo":
                await state.set_state(LocationFlow.geolocation)
                keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=i18n.text(user.language, "send-location"), request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
                await callback.message.answer(i18n.text(user.language, "send-location"), reply_markup=keyboard)  # temporary, allowed only here
            elif action == "radius":
                place = (await state.get_data()).get("place")
                if not place:
                    await render_location(callback.bot, session, user)
                else:
                    await save_search(session, user, place, callback_data.entity)
                    await state.clear(); await main_screen(callback.bot, session, user, nav)
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
            places = await geocoder.search(message.text, user.language)
            await present_places(message.bot, session, user, state, places)
            await session.commit()

    @router.message(LocationFlow.geolocation)
    async def geolocation(message: Message, state: FSMContext) -> None:
        if not message.location: return
        async with session_factory() as session:
            user = await user_for(message, session)
            await message.answer(i18n.text(user.language, "saved"), reply_markup=ReplyKeyboardRemove())
            places = await geocoder.reverse(message.location.latitude, message.location.longitude, user.language)
            await present_places(message.bot, session, user, state, places)
            await session.commit()

    async def present_places(bot: Bot, session: AsyncSession, user: User, state: FSMContext, places: list[GeocodedPlace]) -> None:
        await state.update_data(places=[place.__dict__ for place in places])
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        version = user.active_navigation_version + 1
        rows = [[InlineKeyboardButton(text=place.display_name, callback_data=NavCallback(action="place", entity=index, version=version).pack())] for index, place in enumerate(places[:5])]
        rows.append([InlineKeyboardButton(text=i18n.text(user.language, "back"), callback_data=NavCallback(action="location", version=version).pack())])
        await nav.render_text_screen(bot, session, user, i18n.text(user.language, "choose-location"), InlineKeyboardMarkup(inline_keyboard=rows), "place-selection")
        await state.set_state(LocationFlow.place_selection)

    async def save_search(session: AsyncSession, user: User, raw: dict[str, object], radius: int) -> Search:
        if radius:
            bounds = radius_bounds(float(raw["latitude"]), float(raw["longitude"]), radius)
        else:
            bounds = validate_bounds(Bounds(float(raw["west"]), float(raw["north"]), float(raw["east"]), float(raw["south"])))
        search = Search(user_id=user.id, location_display_name=str(raw["display_name"]), city=raw.get("city"), postal_code=raw.get("postal_code"), country_code=raw.get("country_code"), center_latitude=float(raw["latitude"]), center_longitude=float(raw["longitude"]), radius_km=radius or None, bounds_west=bounds.west, bounds_north=bounds.north, bounds_east=bounds.east, bounds_south=bounds.south, next_check_at=datetime.now(UTC))
        session.add(search); await session.flush(); return search

    async def send_current_listings(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
        search = await latest_search(session, user)
        if not search:
            await callback.answer(i18n.text(user.language, "no-search"), show_alert=True); return
        listings = await crous.search(Bounds(search.bounds_west, search.bounds_north, search.bounds_east, search.bounds_south))
        from app.bot.cards import send_accommodation_card
        for listing in listings[:5]:
            await send_accommodation_card(callback.bot, user.telegram_chat_id, listing, user.language, datetime.now(UTC))
        await main_screen(callback.bot, session, user, nav)

    return router
