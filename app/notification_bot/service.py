from __future__ import annotations

from aiogram import Bot

from app.core.config import Settings


class NotificationBotUnavailable(RuntimeError):
    pass


async def send_operational_notification(settings: Settings, text: str) -> None:
    """Send one server-originated operational alert through the separate bot."""
    if settings.notification_bot_token is None:
        raise NotificationBotUnavailable("Notification bot is not configured")
    token = settings.notification_bot_token.get_secret_value()
    bot = Bot(token)
    try:
        for chat_id in settings.admin_notification_chat_id_set:
            await bot.send_message(chat_id, text)
    finally:
        await bot.session.close()
