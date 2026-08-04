from __future__ import annotations

import asyncio
from urllib.parse import urlencode

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from app.admin.security import normalize_username
from app.core.config import get_settings
from app.db.models import ReferralProgram
from app.db.session import SessionLocal
from app.referrals.service import bind_owner, issue_owner_login_token


def build_router() -> Router:
    router = Router(name="referral-owner")

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        if message.from_user is None or not message.from_user.username:
            await message.answer("Set a Telegram username and send /start again.")
            return
        _, key = normalize_username(message.from_user.username)
        async with SessionLocal() as session:
            program = await session.scalar(
                select(ReferralProgram).where(ReferralProgram.owner_username_key == key)
            )
            if program is None or not await bind_owner(session, program, message.from_user.id):
                await message.answer("No referral program is linked to this Telegram account.")
                return
            settings = get_settings()
            if settings.referral_stats_base_url is None:
                await message.answer("Referral statistics are not configured yet.")
                return
            token = await issue_owner_login_token(
                session, program, settings.referral_login_token_ttl_minutes
            )
            await session.commit()
        url = f"{str(settings.referral_stats_base_url).rstrip('/')}?{urlencode({'token': token})}"
        await message.answer(
            f"Open your secure referral statistics link (valid for {settings.referral_login_token_ttl_minutes} minutes): {url}"
        )

    return router


async def main() -> None:
    settings = get_settings()
    if settings.referral_bot_token is None:
        raise RuntimeError("REFERRAL_BOT_TOKEN is required")
    bot = Bot(settings.referral_bot_token.get_secret_value())
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
