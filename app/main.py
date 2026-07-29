from __future__ import annotations

from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.bot.handlers.main import build_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.crous.client import CrousClient
from app.db.session import SessionLocal
from app.geocoding.provider import PhotonProvider
from app.payments.stripe import StripeError, process_checkout_completed, verify_webhook

settings = get_settings()
bot: Bot | None = None
dispatcher: Dispatcher | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global bot, dispatcher
    configure_logging(settings.log_level)
    if settings.telegram_bot_token:
        bot = Bot(
            settings.telegram_bot_token.get_secret_value(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dispatcher = Dispatcher(storage=RedisStorage.from_url(settings.redis_url))
        dispatcher.include_router(build_router(SessionLocal, PhotonProvider(), CrousClient(settings)))
        if settings.run_mode == "webhook" and settings.public_base_url and settings.webhook_secret:
            await bot.set_webhook(f"{str(settings.public_base_url).rstrip('/')}{settings.telegram_webhook_path}", secret_token=settings.webhook_secret.get_secret_value())
    yield
    if bot: await bot.session.close()


app = FastAPI(title="CROUS Logement Bot", lifespan=lifespan)


def payment_page(title: str, message: str) -> HTMLResponse:
    bot_url = str(settings.telegram_bot_url or "https://t.me/")
    return HTMLResponse(
        f"<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><title>{title}</title>"
        f"<body><main><h1>{title}</h1><p>{message}</p>"
        f"<p><a href=\"{bot_url}\">Open the Telegram bot</a></p></main></body></html>"
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    client = CrousClient(settings)
    try: healthy = await client.health_check()
    finally: await client.close()
    if not healthy: raise HTTPException(503, "CROUS unavailable")
    return {"status": "ok"}


@app.get(settings.payment_success_path)
async def payment_success() -> HTMLResponse:
    return payment_page("Payment received", "Your access is activated only after Stripe verifies the payment.")


@app.get(settings.payment_cancel_path)
async def payment_cancel() -> HTMLResponse:
    return payment_page("Payment cancelled", "No subscription was activated. You can return to the bot and try again.")


@app.post(settings.telegram_webhook_path)
async def telegram_webhook(update: dict[str, object], x_telegram_bot_api_secret_token: str | None = Header(default=None)) -> dict[str, bool]:
    if not bot or not dispatcher or not settings.webhook_secret:
        raise HTTPException(503, "Webhook is not configured")
    if x_telegram_bot_api_secret_token != settings.webhook_secret.get_secret_value():
        raise HTTPException(403, "Invalid webhook secret")
    from aiogram.types import Update
    await dispatcher.feed_update(bot, Update.model_validate(update))
    return {"ok": True}


@app.post(settings.stripe_webhook_path)
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None)) -> dict[str, bool]:
    """Stripe is the sole payment activation authority; browser redirects do nothing."""
    if not settings.stripe_webhook_secret:
        raise HTTPException(503, "Stripe webhook is not configured")
    try:
        event = verify_webhook(await request.body(), stripe_signature, settings.stripe_webhook_secret.get_secret_value())
    except StripeError as error:
        raise HTTPException(400, "Invalid Stripe webhook") from error
    try:
        async with SessionLocal() as session:
            payment = await process_checkout_completed(session, event, settings)
            await session.commit()
        if payment and not payment.duplicate and bot:
            from app.core.i18n import i18n
            await bot.send_message(
                payment.user.telegram_chat_id,
                i18n.text(payment.user.language, "payment-confirmed", plan=i18n.text(payment.user.language, f"plan-{payment.plan.code}")),
            )
    except StripeError as error:
        raise HTTPException(400, "Stripe payment could not be processed") from error
    return {"ok": True}
