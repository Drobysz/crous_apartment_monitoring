from __future__ import annotations

from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from fastapi import FastAPI, Header, HTTPException

from app.bot.handlers.main import build_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.crous.client import CrousClient
from app.db.session import SessionLocal
from app.geocoding.provider import PhotonProvider

settings = get_settings()
bot: Bot | None = None
dispatcher: Dispatcher | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global bot, dispatcher
    configure_logging(settings.log_level)
    if settings.telegram_bot_token:
        bot = Bot(settings.telegram_bot_token.get_secret_value())
        dispatcher = Dispatcher(storage=RedisStorage.from_url(settings.redis_url))
        dispatcher.include_router(build_router(SessionLocal, PhotonProvider(), CrousClient(settings)))
        if settings.run_mode == "webhook" and settings.webhook_base_url and settings.webhook_secret:
            await bot.set_webhook(f"{str(settings.webhook_base_url).rstrip('/')}/telegram/webhook", secret_token=settings.webhook_secret.get_secret_value())
    yield
    if bot: await bot.session.close()


app = FastAPI(title="CROUS Logement Bot", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    client = CrousClient(settings)
    try: healthy = await client.health_check()
    finally: await client.close()
    if not healthy: raise HTTPException(503, "CROUS unavailable")
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(update: dict[str, object], x_telegram_bot_api_secret_token: str | None = Header(default=None)) -> dict[str, bool]:
    if not bot or not dispatcher or not settings.webhook_secret:
        raise HTTPException(503, "Webhook is not configured")
    if x_telegram_bot_api_secret_token != settings.webhook_secret.get_secret_value():
        raise HTTPException(403, "Invalid webhook secret")
    from aiogram.types import Update
    await dispatcher.feed_update(bot, Update.model_validate(update))
    return {"ok": True}
