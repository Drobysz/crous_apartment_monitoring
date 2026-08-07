from __future__ import annotations

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import Admin, AdminNotificationChat
from app.db.session import SessionLocal


class NotificationBotUnavailable(RuntimeError):
    pass


def username_key(username: str | None) -> str | None:
    if not username:
        return None
    normalized = username.strip().lstrip("@").casefold()
    return normalized or None


def telegram_username_handle(username: str | None) -> str | None:
    """Return Telegram's username in the canonical @username form."""
    key = username_key(username)
    return f"@{key}" if key is not None else None


async def register_admin_notification_chat(
    session: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    telegram_username: str | None,
) -> bool:
    """Register a private chat only when Telegram's username matches an active admin."""
    key = username_key(telegram_username)
    if key is None:
        return False
    admin = await session.scalar(
        select(Admin).where(Admin.username_key == key, Admin.is_active.is_(True))
    )
    if admin is None:
        return False
    chat = await session.scalar(
        select(AdminNotificationChat).where(
            AdminNotificationChat.telegram_chat_id == telegram_chat_id
        )
    )
    if chat is None:
        chat = AdminNotificationChat(
            admin_id=admin.id,
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
        )
        session.add(chat)
    else:
        chat.admin_id = admin.id
        chat.telegram_user_id = telegram_user_id
    await session.flush()
    return True


async def active_notification_chat_ids(session: AsyncSession) -> list[int]:
    """Return chats that remain attached to active administrator accounts."""
    return list(
        await session.scalars(
            select(AdminNotificationChat.telegram_chat_id)
            .join(Admin, Admin.id == AdminNotificationChat.admin_id)
            .where(Admin.is_active.is_(True))
        )
    )


async def send_operational_notification(
    settings: Settings,
    text: str,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> None:
    """Send alerts only to private chats registered by active admins via username."""
    if settings.notification_bot_token is None:
        raise NotificationBotUnavailable("Notification bot is not configured")
    token = settings.notification_bot_token.get_secret_value()
    bot = Bot(token)
    try:
        async with session_factory() as session:
            chat_ids = await active_notification_chat_ids(session)
        for chat_id in chat_ids:
            await bot.send_message(chat_id, text)
    finally:
        await bot.session.close()
