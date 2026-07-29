from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.i18n import detect_language, i18n
from app.notification_bot.service import register_admin_notification_chat


def build_router(session_factory: async_sessionmaker[AsyncSession]) -> Router:
    router = Router(name="notification_bot")

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        source = message.from_user
        language = detect_language(source.language_code if source else None)
        if message.chat.type != ChatType.PRIVATE:
            await message.answer(i18n.text(language, "notification-bot-private-chat-required"))
            return
        if source is None or not source.username:
            await message.answer(i18n.text(language, "notification-bot-username-required"))
            return
        async with session_factory() as session:
            allowed = await register_admin_notification_chat(
                session,
                telegram_chat_id=message.chat.id,
                telegram_user_id=source.id,
                telegram_username=source.username,
            )
            if allowed:
                await session.commit()
        await message.answer(i18n.text(language, "notification-bot-ready" if allowed else "notification-bot-access-denied"))

    return router
