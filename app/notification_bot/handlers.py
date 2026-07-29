from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.core.i18n import detect_language, i18n


def build_router() -> Router:
    router = Router(name="notification_bot")

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        await message.answer(i18n.text(detect_language(message.from_user.language_code if message.from_user else None), "notification-bot-ready"))

    return router
