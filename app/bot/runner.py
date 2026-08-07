import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from app.bot.handlers.main import build_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.crous.client import CrousClient
from app.db.session import SessionLocal
from app.geocoding.provider import PhotonProvider


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    configure_logging(settings.log_level)
    bot = Bot(
        settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=RedisStorage.from_url(settings.redis_url))
    dispatcher.include_router(build_router(SessionLocal, PhotonProvider(), CrousClient(settings)))
    await bot.delete_webhook(drop_pending_updates=False)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
