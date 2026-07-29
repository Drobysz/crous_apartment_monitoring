from __future__ import annotations

import httpx
import structlog
from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.callbacks import NavCallback
from app.bot.cards import send_accommodation_card
from app.bot.keyboards import back, language_menu, location_menu, radius_menu
from app.bot.navigation.manager import NavigationMessageManager
from app.bot.services import get_or_create_user, latest_search, main_screen
from app.bot.states import FilterFlow, LocationFlow
from app.core.config import get_settings
from app.core.i18n import i18n
from app.crous.client import CrousClient
from app.crous.exceptions import CrousUnavailable
from app.crous.models import CrousListing
from app.db.models import Listing, Search, SearchListing, User
from app.geocoding.base import GeocodingProvider
from app.geocoding.models import GeocodedPlace
from app.monitoring.locks import SearchLock
from app.monitoring.service import SnapshotDeliveryError, synchronize_search
from app.payments.stripe import StripeError, create_checkout_session
from app.searches.filters import FilterValidationError, parse_price_range, parse_surface_range
from app.searches.service import (
    InvalidBounds,
    bounds_from_serialized,
    radius_bounds,
)
from app.subscriptions.service import (
    activate_trial,
    can_check_now,
    can_use_advanced_filters,
    get_effective_subscription,
    get_pending_subscription,
    paid_plans,
    plan_features,
    plan_interval,
    reset_current_subscription,
)

logger = structlog.get_logger(__name__)


def build_router(session_factory: async_sessionmaker[AsyncSession], geocoder: GeocodingProvider, crous: CrousClient) -> Router:
    router = Router(name="main")
    nav = NavigationMessageManager()

    async def run_search_sync(search_id: int, bot: Bot, correlation_id: str) -> str:
        settings = get_settings()
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            async with SearchLock(redis, search_id, settings.monitoring_lock_ttl_seconds) as acquired:
                if not acquired:
                    return "busy"
                return await synchronize_search(session_factory, bot, crous, search_id, correlation_id=correlation_id)
        finally:
            await redis.aclose()

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

    def money(value: int | None) -> str:
        return "—" if value is None else f"€{value / 100:g}"

    async def render_filters(bot: Bot, session: AsyncSession, user: User) -> None:
        search = await latest_search(session, user)
        language, version = user.language, user.active_navigation_version + 1
        if search is None:
            await nav.render_text_screen(bot, session, user, i18n.text(language, "no-search"), back(language, version), "filters")
            return
        if not await can_use_advanced_filters(session, user):
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=i18n.text(language, "subscription"), callback_data=NavCallback(action="subscription", version=version).pack())],
                [InlineKeyboardButton(text=i18n.text(language, "back"), callback_data=NavCallback(action="menu", version=version).pack())],
            ])
            await nav.render_text_screen(bot, session, user, i18n.text(language, "filters-requires-premium"), keyboard, "filters-locked")
            return
        price = i18n.text(language, "not-set") if search.price_min_cents is None else f"{money(search.price_min_cents)}–{money(search.price_max_cents)}"
        surface = i18n.text(language, "not-set") if search.surface_min_m2 is None else f"{search.surface_min_m2:g}–{search.surface_max_m2:g} m²"
        format_value = i18n.text(language, "not-set") if not search.accommodation_format else i18n.text(language, f"format-{search.accommodation_format}")
        text = i18n.text(language, "filters-page", price=price, surface=surface, format=format_value)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=i18n.text(language, "filter-price", value=price), callback_data=NavCallback(action="filter-price", version=version).pack())],
            [InlineKeyboardButton(text=i18n.text(language, "filter-surface", value=surface), callback_data=NavCallback(action="filter-surface", version=version).pack())],
            [InlineKeyboardButton(text=i18n.text(language, "filter-format", value=format_value), callback_data=NavCallback(action="filter-format", version=version).pack())],
            [InlineKeyboardButton(text=i18n.text(language, "clear-filters"), callback_data=NavCallback(action="filter-clear", version=version).pack())],
            [InlineKeyboardButton(text=i18n.text(language, "back"), callback_data=NavCallback(action="menu", version=version).pack())],
        ])
        await nav.render_text_screen(bot, session, user, text, keyboard, "filters")

    async def render_subscription(bot: Bot, session: AsyncSession, user: User) -> None:
        effective = await get_effective_subscription(session, user)
        language, version = user.language, user.active_navigation_version + 1
        ends = effective.entitlement.ends_at.strftime("%d/%m/%Y") if effective.entitlement and effective.entitlement.ends_at else i18n.text(language, "unlimited")
        starts = effective.entitlement.starts_at.strftime("%d/%m/%Y") if effective.entitlement else "—"
        interval = i18n.text(language, "interval-minutes", count=max(1, plan_interval(effective.plan) // 60))
        features = ", ".join(i18n.text(language, f"feature-{feature}") for feature in plan_features(effective.plan)) or i18n.text(language, "feature-basic")
        text = i18n.text(language, "subscription-page", plan=i18n.text(language, f"plan-{effective.plan.code}"), starts=starts, ends=ends, interval=interval, features=features)
        pending = await get_pending_subscription(session, user)
        if pending and pending.entitlement:
            text += "\n\n" + i18n.text(language, "pending-subscription", plan=i18n.text(language, f"plan-{pending.plan.code}"), starts=pending.entitlement.starts_at.strftime("%d/%m/%Y"))
        rows: list[list[InlineKeyboardButton]] = []
        if user.trial_used_at is None:
            rows.append([InlineKeyboardButton(text=i18n.text(language, "start-trial"), callback_data=NavCallback(action="trial", version=version).pack())])
        for index, plan in enumerate(await paid_plans(session)):
            price = money(plan.price_cents)
            rows.append([InlineKeyboardButton(text=i18n.text(language, "plan-button", plan=i18n.text(language, f"plan-{plan.code}"), price=price), callback_data=NavCallback(action="subplan", entity=index, version=version).pack())])
        rows.append([InlineKeyboardButton(text=i18n.text(language, "back"), callback_data=NavCallback(action="menu", version=version).pack())])
        await nav.render_text_screen(bot, session, user, text, InlineKeyboardMarkup(inline_keyboard=rows), "subscription")

    async def render_plan_detail(bot: Bot, session: AsyncSession, user: User, index: int) -> None:
        plans = await paid_plans(session)
        if index < 0 or index >= len(plans):
            await render_subscription(bot, session, user); return
        plan, language, version = plans[index], user.language, user.active_navigation_version + 1
        validity = i18n.text(language, "unlimited") if plan.code == "lifetime" else i18n.text(language, "plan-validity", code=plan.code)
        text = i18n.text(language, "plan-detail", plan=i18n.text(language, f"plan-{plan.code}"), price=money(plan.price_cents), validity=validity)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=i18n.text(language, "buy"), callback_data=NavCallback(action="buy", entity=index, version=version).pack())],
            [InlineKeyboardButton(text=i18n.text(language, "back"), callback_data=NavCallback(action="subscription", version=version).pack())],
        ])
        await nav.render_text_screen(bot, session, user, text, keyboard, "subscription-detail")

    async def render_monitoring(bot: Bot, session: AsyncSession, user: User) -> None:
        search, language, version = await latest_search(session, user), user.language, user.active_navigation_version + 1
        enabled = bool(search and search.is_active)
        action = "monitor-disable-confirm" if enabled else "monitor-enable"
        label = "disable-monitoring" if enabled else "enable-monitoring"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=i18n.text(language, label), callback_data=NavCallback(action=action, version=version).pack())],
            [InlineKeyboardButton(text=i18n.text(language, "back"), callback_data=NavCallback(action="menu", version=version).pack())],
        ])
        await nav.render_text_screen(bot, session, user, i18n.text(language, "monitoring-page", status=i18n.text(language, "enabled" if enabled else "disabled")), keyboard, "monitoring")

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
            if await can_check_now(session, user):
                await send_current_listings_from_message(message, session, user)
            else:
                await message.answer(i18n.text(user.language, "check-now-requires-premium"))
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
                languages = ("en", "ru", "uk", "tr", "fa", "fr", "ar")
                if callback_data.entity < len(languages):
                    user.language = languages[callback_data.entity]
                await main_screen(callback.bot, session, user, nav)
            elif action == "filters":
                await state.clear(); await render_filters(callback.bot, session, user)
            elif action == "filter-price":
                if not await can_use_advanced_filters(session, user):
                    await render_filters(callback.bot, session, user)
                else:
                    await state.set_state(FilterFlow.price_input)
                    version = user.active_navigation_version + 1
                    await nav.render_text_screen(callback.bot, session, user, i18n.text(user.language, "price-input"), back(user.language, version, "filters"), "filter-price-input")
            elif action == "filter-surface":
                if not await can_use_advanced_filters(session, user):
                    await render_filters(callback.bot, session, user)
                else:
                    await state.set_state(FilterFlow.surface_input)
                    version = user.active_navigation_version + 1
                    await nav.render_text_screen(callback.bot, session, user, i18n.text(user.language, "surface-input"), back(user.language, version, "filters"), "filter-surface-input")
            elif action == "filter-format":
                version = user.active_navigation_version + 1
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=i18n.text(user.language, "format-individuel"), callback_data=NavCallback(action="format", entity=1, version=version).pack())],
                    [InlineKeyboardButton(text=i18n.text(user.language, "format-colocation"), callback_data=NavCallback(action="format", entity=2, version=version).pack())],
                    [InlineKeyboardButton(text=i18n.text(user.language, "format-any"), callback_data=NavCallback(action="format", entity=0, version=version).pack())],
                    [InlineKeyboardButton(text=i18n.text(user.language, "back"), callback_data=NavCallback(action="filters", version=version).pack())],
                ])
                await nav.render_text_screen(callback.bot, session, user, i18n.text(user.language, "format-input"), keyboard, "filter-format")
            elif action == "format":
                search = await latest_search(session, user)
                if search and await can_use_advanced_filters(session, user):
                    search.accommodation_format = (None, "individuel", "colocation")[callback_data.entity] if callback_data.entity < 3 else None
                await render_filters(callback.bot, session, user)
            elif action == "filter-clear":
                search = await latest_search(session, user)
                if search and await can_use_advanced_filters(session, user):
                    search.price_min_cents = search.price_max_cents = None
                    search.surface_min_m2 = search.surface_max_m2 = None
                    search.accommodation_format = None
                await render_filters(callback.bot, session, user)
            elif action == "subscription":
                await state.clear(); await render_subscription(callback.bot, session, user)
            elif action == "trial":
                entitlement = await activate_trial(session, user)
                await render_subscription(callback.bot, session, user)
                if entitlement:
                    await callback.message.answer(i18n.text(user.language, "trial-started"))
            elif action == "subplan":
                await render_plan_detail(callback.bot, session, user, callback_data.entity)
            elif action == "buy":
                plans = await paid_plans(session)
                if callback_data.entity >= len(plans):
                    await render_subscription(callback.bot, session, user)
                else:
                    try:
                        checkout_url = await create_checkout_session(session, user, plans[callback_data.entity].code)
                    except StripeError:
                        version = user.active_navigation_version + 1
                        await nav.render_text_screen(callback.bot, session, user, i18n.text(user.language, "payment-unavailable"), back(user.language, version, "subscription"), "payment")
                    else:
                        version = user.active_navigation_version + 1
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text=i18n.text(user.language, "open-payment"), url=checkout_url)],
                            [InlineKeyboardButton(text=i18n.text(user.language, "back"), callback_data=NavCallback(action="subscription", version=version).pack())],
                        ])
                        await nav.render_text_screen(callback.bot, session, user, i18n.text(user.language, "payment-page"), keyboard, "payment")
            elif action == "monitoring":
                await state.clear(); await render_monitoring(callback.bot, session, user)
            elif action == "monitor-disable-confirm":
                version = user.active_navigation_version + 1
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=i18n.text(user.language, "disable-monitoring"), callback_data=NavCallback(action="monitor-disable", version=version).pack())],
                    [InlineKeyboardButton(text=i18n.text(user.language, "back"), callback_data=NavCallback(action="monitoring", version=version).pack())],
                ])
                await nav.render_text_screen(callback.bot, session, user, i18n.text(user.language, "disable-monitoring-confirm"), keyboard, "monitoring-confirm")
            elif action in {"monitor-disable", "monitor-enable"}:
                search = await latest_search(session, user)
                if search:
                    search.is_active = action == "monitor-enable"
                await render_monitoring(callback.bot, session, user)
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
                location_keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=i18n.text(user.language, "send-location"), request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
                await callback.message.answer(i18n.text(user.language, "send-location"), reply_markup=location_keyboard)  # temporary, allowed only here
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
                await send_stored_listings(callback, session, user)
            elif action == "check-now":
                if await can_check_now(session, user):
                    await send_current_listings(callback, session, user)
                else:
                    version = user.active_navigation_version + 1
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=i18n.text(user.language, "subscription"), callback_data=NavCallback(action="subscription", version=version).pack())],
                        [InlineKeyboardButton(text=i18n.text(user.language, "back"), callback_data=NavCallback(action="menu", version=version).pack())],
                    ])
                    await nav.render_text_screen(callback.bot, session, user, i18n.text(user.language, "check-now-requires-premium"), keyboard, "check-now-locked")
            elif action == "test-reset":
                if get_settings().is_developer(user.telegram_user_id):
                    removed = await reset_current_subscription(session, user)
                    await main_screen(
                        callback.bot,
                        session,
                        user,
                        nav,
                        notice=i18n.text(user.language, "test-reset-done" if removed else "test-reset-none"),
                    )
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

    @router.message(FilterFlow.price_input)
    async def price_input(message: Message, state: FSMContext) -> None:
        if not message.text:
            return
        async with session_factory() as session:
            user = await user_for(message, session)
            search = await latest_search(session, user)
            try:
                if search is None:
                    raise FilterValidationError("No search")
                if message.text.strip().casefold() == "clear":
                    search.price_min_cents = search.price_max_cents = None
                else:
                    search.price_min_cents, search.price_max_cents = parse_price_range(message.text)
            except FilterValidationError:
                version = user.active_navigation_version + 1
                await nav.render_text_screen(message.bot, session, user, i18n.text(user.language, "range-invalid"), back(user.language, version, "filters"), "filter-price-input")
            else:
                await state.clear()
                await render_filters(message.bot, session, user)
            await session.commit()

    @router.message(FilterFlow.surface_input)
    async def surface_input(message: Message, state: FSMContext) -> None:
        if not message.text:
            return
        async with session_factory() as session:
            user = await user_for(message, session)
            search = await latest_search(session, user)
            try:
                if search is None:
                    raise FilterValidationError("No search")
                if message.text.strip().casefold() == "clear":
                    search.surface_min_m2 = search.surface_max_m2 = None
                else:
                    search.surface_min_m2, search.surface_max_m2 = parse_surface_range(message.text)
            except FilterValidationError:
                version = user.active_navigation_version + 1
                await nav.render_text_screen(message.bot, session, user, i18n.text(user.language, "range-invalid"), back(user.language, version, "filters"), "filter-surface-input")
            else:
                await state.clear()
                await render_filters(message.bot, session, user)
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
            "is_active": True,
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
        correlation_id = callback.id
        loading_message = await callback.message.answer(i18n.text(user.language, "list-loading"))
        try:
            result = await run_search_sync(search.id, callback.bot, correlation_id)
            if result == "busy":
                await callback.message.answer(i18n.text(user.language, "list-loading"))
            elif result == "unchanged":
                await callback.answer(i18n.text(user.language, "list-current"), show_alert=False)
        except (SnapshotDeliveryError, CrousUnavailable, httpx.HTTPError) as error:
            logger.warning("listing_request_failed", correlation_id=correlation_id, telegram_user_id=user.telegram_user_id, search_id=search.id, reason=str(error))
            await callback.message.answer(i18n.text(user.language, "error"))
        finally:
            try:
                await loading_message.delete()
            except TelegramBadRequest:
                pass

    async def send_stored_listings(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
        search = await latest_search(session, user)
        if search is None:
            await callback.answer(i18n.text(user.language, "no-search"), show_alert=True)
            return
        version = user.active_navigation_version + 1
        await nav.render_text_screen(callback.bot, session, user, i18n.text(user.language, "list-loading"), back(user.language, version), "list")
        rows = await session.scalars(
            select(Listing).join(SearchListing, SearchListing.listing_id == Listing.id).where(SearchListing.search_id == search.id, SearchListing.is_currently_available.is_(True)).order_by(Listing.last_seen_at.desc())
        )
        listings = list(rows)
        for listing in listings:
            item = CrousListing(
                external_id=listing.external_id, canonical_url=listing.canonical_url, title=listing.title,
                residence_name=listing.residence_name, address=listing.address, latitude=listing.latitude, longitude=listing.longitude,
                price_cents=listing.price_cents, price_original=listing.price_original, surface_min=listing.surface_min, surface_max=listing.surface_max,
                surface_original=listing.surface_original, occupancy_type=listing.occupancy_type, bed_information=listing.bed_information,
                sanitary_information=listing.sanitary_information, kitchen_information=listing.kitchen_information, equipment=listing.equipment,
                primary_image_url=listing.primary_image_url, raw_payload=listing.raw_payload,
            )
            await send_accommodation_card(callback.bot, user.telegram_chat_id, item, user.language, listing.first_seen_at)
        version = user.active_navigation_version + 1
        await nav.render_text_screen(
            callback.bot, session, user,
            i18n.text(user.language, "list-result", count=len(listings)), back(user.language, version), "list",
        )

    async def send_current_listings_from_message(
        message: Message,
        session: AsyncSession,
        user: User,
    ) -> None:
        search = await latest_search(session, user)
        if not search:
            await message.answer(i18n.text(user.language, "no-search"))
            return
        correlation_id = f"command:{message.message_id}"
        loading_message = await message.answer(i18n.text(user.language, "list-loading"))
        try:
            result = await run_search_sync(search.id, message.bot, correlation_id)
            if result == "busy":
                await message.answer(i18n.text(user.language, "list-loading"))
            elif result == "unchanged":
                await message.answer(i18n.text(user.language, "list-current"))
        except (SnapshotDeliveryError, CrousUnavailable, httpx.HTTPError) as error:
            logger.warning("listing_request_failed", correlation_id=correlation_id, telegram_user_id=user.telegram_user_id, search_id=search.id, reason=str(error))
            await message.answer(i18n.text(user.language, "error"))
        finally:
            try:
                await loading_message.delete()
            except TelegramBadRequest:
                pass

    return router
