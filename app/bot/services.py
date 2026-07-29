from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import main_menu
from app.bot.navigation.manager import NavigationMessageManager
from app.core.config import get_settings
from app.core.i18n import i18n
from app.db.models import Search, SearchListing, User
from app.subscriptions.service import get_effective_subscription


async def get_or_create_user(
    session: AsyncSession,
    telegram_user_id: int,
    chat_id: int,
    telegram_language_code: str | None,
    telegram_username: str | None = None,
) -> User:
    from app.core.i18n import detect_language
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        user = User(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=chat_id,
            telegram_username=telegram_username.casefold() if telegram_username else None,
            telegram_language_code=telegram_language_code,
            language=detect_language(telegram_language_code),
        )
        session.add(user)
        await session.flush()
    else:
        user.telegram_chat_id = chat_id
        user.telegram_username = telegram_username.casefold() if telegram_username else None
    return user


async def latest_search(session: AsyncSession, user: User) -> Search | None:
    return await session.scalar(select(Search).where(Search.user_id == user.id).order_by(Search.id.desc()))


async def available_listing_count(session: AsyncSession, search: Search | None) -> int:
    """Return the current availability for one search, not a global listing count."""
    if search is None:
        return 0
    count = await session.scalar(
        select(func.count())
        .select_from(SearchListing)
        .where(
            SearchListing.search_id == search.id,
            SearchListing.is_currently_available.is_(True),
        )
    )
    return int(count or 0)


def format_last_check(value: datetime | None) -> str:
    if value is None:
        return "—"
    try:
        timezone = ZoneInfo(get_settings().display_timezone)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return value.astimezone(timezone).strftime("%d/%m %H:%M")


async def main_screen_text(session: AsyncSession, user: User, *, notice: str | None = None) -> str:
    search = await latest_search(session, user)
    language = user.language
    location = search.location_display_name if search else "—"
    last_check = format_last_check(search.last_success_at if search else None)
    last_change = format_last_check(search.last_changed_at if search else None)
    enabled = bool(search and search.is_active)
    effective = await get_effective_subscription(session, user)
    available_count = await available_listing_count(session, search)
    parts = [i18n.text(language, "main-title")]
    if notice:
        parts.append(notice)
    parts.extend(
        [
            i18n.text(language, "area", value=location),
            i18n.text(
                language,
                "monitoring",
                value=i18n.text(language, "enabled" if enabled else "disabled"),
            ),
            i18n.text(language, "current-plan", value=i18n.text(language, f"plan-{effective.plan.code}")),
            i18n.text(language, "available-count", count=available_count),
            i18n.text(language, "last-check", value=last_check),
            i18n.text(language, "last-change", value=last_change),
        ]
    )
    return "\n\n".join(parts)


async def main_screen(
    bot: Bot,
    session: AsyncSession,
    user: User,
    nav: NavigationMessageManager,
    *,
    notice: str | None = None,
    force_new: bool = False,
) -> None:
    text = await main_screen_text(session, user, notice=notice)
    search = await latest_search(session, user)
    version = user.active_navigation_version + 1
    await nav.render_text_screen(
        bot,
        session,
        user,
        text,
        main_menu(
            user.language,
            version,
            show_test_reset=get_settings().is_developer(user.telegram_user_id),
            monitoring_enabled=bool(search and search.is_active),
        ),
        "main",
        force_new=force_new,
    )


async def refresh_visible_main_screen(bot: Bot, session: AsyncSession, user: User) -> None:
    """Refresh an already visible main menu after a background monitor run."""
    if (
        user.active_navigation_screen != "main"
        or user.active_navigation_chat_id is None
        or user.active_navigation_message_id is None
    ):
        return
    try:
        search = await latest_search(session, user)
        await bot.edit_message_text(
            await main_screen_text(session, user),
            chat_id=user.active_navigation_chat_id,
            message_id=user.active_navigation_message_id,
            reply_markup=main_menu(
                user.language,
                user.active_navigation_version,
                show_test_reset=get_settings().is_developer(user.telegram_user_id),
                monitoring_enabled=bool(search and search.is_active),
            ),
        )
    except TelegramBadRequest:
        # The user may have deleted the navigation message. The next command
        # or button interaction creates a fresh one.
        return
