from __future__ import annotations

from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from fastapi import FastAPI, Header, HTTPException

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.notification_bot.handlers import build_router

settings = get_settings()
bot: Bot | None = None
dispatcher = Dispatcher()
dispatcher.include_router(build_router(SessionLocal))


async def configure_webhook(notification_bot: Bot, configured_settings: Settings) -> None:
    """Register the public notification-bot webhook during a webhook deployment."""
    if configured_settings.run_mode != "webhook" or configured_settings.notification_webhook_secret is None:
        return
    webhook_url = f"{str(configured_settings.public_base_url).rstrip('/')}{configured_settings.notification_bot_webhook_path}"
    await notification_bot.set_webhook(
        webhook_url,
        secret_token=configured_settings.notification_webhook_secret.get_secret_value(),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    global bot
    if settings.notification_bot_token is not None:
        bot = Bot(settings.notification_bot_token.get_secret_value())
        await configure_webhook(bot, settings)
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
