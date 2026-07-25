from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class NavigationMessageManager:
    """Maintains one mutable navigation message without touching accommodation cards."""
    async def render_text_screen(
        self,
        bot: Bot,
        session: AsyncSession,
        user: User,
        text: str,
        keyboard: InlineKeyboardMarkup,
        screen: str,
        *,
        force_new: bool = False,
    ) -> None:
        version = user.active_navigation_version + 1
        if force_new:
            await self.disable_old_keyboard(bot, user)
            message = await bot.send_message(user.telegram_chat_id, text, reply_markup=keyboard)
            user.active_navigation_chat_id, user.active_navigation_message_id = (
                message.chat.id,
                message.message_id,
            )
        elif user.active_navigation_message_id and user.active_navigation_chat_id:
            try:
                await bot.edit_message_text(
                    text,
                    chat_id=user.active_navigation_chat_id,
                    message_id=user.active_navigation_message_id,
                    reply_markup=keyboard,
                )
            except TelegramBadRequest:
                await self.disable_old_keyboard(bot, user)
                message = await bot.send_message(user.telegram_chat_id, text, reply_markup=keyboard)
                user.active_navigation_chat_id, user.active_navigation_message_id = message.chat.id, message.message_id
        else:
            message = await bot.send_message(user.telegram_chat_id, text, reply_markup=keyboard)
            user.active_navigation_chat_id, user.active_navigation_message_id = message.chat.id, message.message_id
        user.active_navigation_screen = screen
        user.active_navigation_version = version
        await session.flush()

    async def replace_screen(self, *args: object, **kwargs: object) -> None:
        await self.render_text_screen(*args, **kwargs)

    async def close_active_navigation(self, bot: Bot, user: User) -> None:
        await self.disable_old_keyboard(bot, user)
        user.active_navigation_message_id = None
        user.active_navigation_chat_id = None

    async def disable_old_keyboard(self, bot: Bot, user: User) -> None:
        if user.active_navigation_message_id and user.active_navigation_chat_id:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=user.active_navigation_chat_id,
                    message_id=user.active_navigation_message_id,
                    reply_markup=None,
                )
            except TelegramBadRequest:
                pass

    def is_current_callback(self, user: User, chat_id: int, message_id: int, version: int) -> bool:
        return bool(user.active_navigation_chat_id == chat_id and user.active_navigation_message_id == message_id and user.active_navigation_version == version)
