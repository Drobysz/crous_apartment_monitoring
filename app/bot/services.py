from __future__ import annotations

from aiogram import Bot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import main_menu
from app.bot.navigation.manager import NavigationMessageManager
from app.core.i18n import i18n
from app.db.models import Search, SearchListing, User


async def get_or_create_user(session: AsyncSession, telegram_user_id: int, chat_id: int, telegram_language_code: str | None) -> User:
    from app.core.i18n import detect_language
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        user = User(telegram_user_id=telegram_user_id, telegram_chat_id=chat_id, telegram_language_code=telegram_language_code, language=detect_language(telegram_language_code))
        session.add(user)
        await session.flush()
    else:
        user.telegram_chat_id = chat_id
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


async def main_screen(
    bot: Bot,
    session: AsyncSession,
    user: User,
    nav: NavigationMessageManager,
    *,
    notice: str | None = None,
    force_new: bool = False,
) -> None:
    search = await latest_search(session, user)
    language = user.language
    location = search.location_display_name if search else "—"
    interval = (search.check_interval_minutes // 60) if search else 2
    last_check = search.last_success_at.strftime("%d/%m %H:%M") if search and search.last_success_at else "—"
    enabled = bool(search and search.is_active)
    available_count = await available_listing_count(session, search)
    parts = [i18n.text(language, "main-title")]
    if notice:
        parts.append(notice)
    parts.extend(
        [
            i18n.text(language, "area", value=location),
            i18n.text(language, "interval", hours=interval),
            i18n.text(
                language,
                "monitoring",
                value=i18n.text(language, "enabled" if enabled else "disabled"),
            ),
            i18n.text(language, "available-count", count=available_count),
            i18n.text(language, "last-check", value=last_check),
        ]
    )
    text = "\n\n".join(parts)
    version = user.active_navigation_version + 1
    await nav.render_text_screen(
        bot,
        session,
        user,
        text,
        main_menu(language, version),
        "main",
        force_new=force_new,
    )
