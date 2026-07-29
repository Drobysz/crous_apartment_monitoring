from __future__ import annotations

from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from fastapi import FastAPI, Header, HTTPException

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.notification_bot.handlers import build_router

settings = get_settings()
bot: Bot | None = None
dispatcher = Dispatcher()
dispatcher.include_router(build_router(SessionLocal))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global bot
    if settings.notification_bot_token is not None:
        bot = Bot(settings.notification_bot_token.get_secret_value())
    yield
    if bot is not None:
        await bot.session.close()


app = FastAPI(title="CROUS operational notification bot", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(update: dict[str, object], x_telegram_bot_api_secret_token: str | None = Header(default=None)) -> dict[str, bool]:
    if bot is None or settings.notification_webhook_secret is None:
        raise HTTPException(status_code=503, detail="Notification bot webhook is not configured")
    if x_telegram_bot_api_secret_token != settings.notification_webhook_secret.get_secret_value():
        raise HTTPException(status_code=403, detail="Invalid notification bot webhook secret")
    await dispatcher.feed_raw_update(bot, update)
    return {"ok": True}
