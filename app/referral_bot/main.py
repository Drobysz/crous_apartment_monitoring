from __future__ import annotations

import asyncio
from html import escape
from urllib.parse import urlencode

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from app.admin.security import normalize_username
from app.core.config import get_settings
from app.core.i18n import detect_language, i18n
from app.db.models import ReferralProgram
from app.db.session import SessionLocal
from app.referrals.service import bind_owner, issue_owner_login_token


def dashboard_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/referral/dashboard?{urlencode({'token': token})}"


def dashboard_link(language: str, url: str) -> str:
    return (
        f'<a href="{escape(url, quote=True)}">'
        f"{escape(i18n.text(language, 'referral-owner-dashboard-link'))}</a>"
    )


def build_router() -> Router:
    router = Router(name="referral-owner")

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        if message.from_user is None:
            return
        language = detect_language(message.from_user.language_code)
        async with SessionLocal() as session:
            # Numeric Telegram identity is authoritative once a program has been bound.
            program = await session.scalar(
                select(ReferralProgram).where(
                    ReferralProgram.owner_telegram_user_id == message.from_user.id,
                    ReferralProgram.deleted_at.is_(None),
                    ReferralProgram.is_active.is_(True),
                )
            )
            if program is None and message.from_user.username:
                try:
                    _, key = normalize_username(message.from_user.username)
                except ValueError:
                    key = None
                if key is not None:
                    program = await session.scalar(
                        select(ReferralProgram).where(
                            ReferralProgram.owner_username_key == key,
                            ReferralProgram.owner_telegram_user_id.is_(None),
                            ReferralProgram.deleted_at.is_(None),
                            ReferralProgram.is_active.is_(True),
                        )
                    )
            if program is None or not await bind_owner(session, program, message.from_user.id):
                await message.answer(i18n.text(language, "referral-owner-not-found"))
                return
            settings = get_settings()
            if settings.referral_stats_base_url is None:
                await message.answer(i18n.text(language, "referral-owner-unavailable"))
                return
            token = await issue_owner_login_token(
                session, program, settings.referral_login_token_ttl_minutes
            )
            await session.commit()
        url = dashboard_url(str(settings.referral_stats_base_url), token)
        await message.answer(
            dashboard_link(language, url),
            parse_mode=ParseMode.HTML,
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
