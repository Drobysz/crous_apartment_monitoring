from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher

from app.core.config import get_settings
from app.notification_bot.handlers import build_router


async def run() -> None:
    settings = get_settings()
    if settings.notification_bot_token is None:
        raise RuntimeError("NOTIFICATION_BOT_TOKEN is not configured")
    bot = Bot(settings.notification_bot_token.get_secret_value())
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
