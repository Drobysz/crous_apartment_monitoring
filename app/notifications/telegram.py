from __future__ import annotations

from aiogram import Bot

from app.core.i18n import i18n


class TelegramNotificationGateway:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_favourite_transition(
        self, *, recipient_id: int, language: str, title: str, transition: str
    ) -> None:
        key = "favorite-appeared" if transition == "appeared" else "favorite-disappeared"
        await self.bot.send_message(recipient_id, i18n.text(language, key, title=title))
