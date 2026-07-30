from __future__ import annotations

from contextlib import asynccontextmanager
from html import escape

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.bot.handlers.main import build_router
from app.bot.navigation.manager import NavigationMessageManager
from app.bot.services import main_screen, refresh_visible_main_screen
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.crous.client import CrousClient
from app.db.models import User
from app.db.session import SessionLocal
from app.geocoding.provider import PhotonProvider
from app.notification_bot.service import NotificationBotUnavailable, send_operational_notification
from app.payments.stripe import (
    ProcessedPayment,
    StripeError,
    process_checkout_completed,
    process_paid_checkout,
    retrieve_checkout_session,
    valid_payment_return_token,
    verify_webhook,
)

settings = get_settings()
bot: Bot | None = None
dispatcher: Dispatcher | None = None
logger = structlog.get_logger(__name__)


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


def payment_page(title: str, message: str, *, successful: bool) -> HTMLResponse:
    bot_url = str(settings.telegram_bot_url or "https://t.me/")
    return HTMLResponse(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)}</title><style>"
        "*{box-sizing:border-box}html,body{min-height:100%;margin:0}body{display:grid;place-items:center;"
        "background:#f5f5f7;color:#1d1d1f;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display',sans-serif;"
        "padding:24px}main{width:min(100%,460px);text-align:center;background:#fff;border:1px solid #d2d2d7;"
        "border-radius:18px;padding:48px 36px;box-shadow:0 2px 8px rgb(0 0 0 / 8%)}"
        ".mark{width:44px;height:44px;margin:0 auto 24px;border-radius:50%;display:grid;place-items:center;"
        f"background:{'#e8f7ed' if successful else '#fff1f0'};color:{'#1d7a3a' if successful else '#b42318'};font-size:24px}}"
        "h1{font-size:28px;letter-spacing:-.4px;margin:0 0 14px}p{font-size:17px;line-height:1.45;margin:0 0 30px;"
        "color:#424245}a{display:inline-block;background:#0071e3;color:#fff;text-decoration:none;border-radius:980px;"
        "padding:12px 20px;font-size:16px;font-weight:600}a:hover{background:#0077ed}</style></head>"
        f"<body><main><div class=\"mark\">{'✓' if successful else '×'}</div><h1>{escape(title)}</h1>"
        f"<p>{escape(message)}</p><a href=\"{escape(bot_url, quote=True)}\">Return to Telegram</a>"
        "</main></body></html>"
    )


def operational_payment_confirmation(payment: ProcessedPayment) -> str:
    from app.core.i18n import i18n

    username = payment.user.telegram_username
    recipient = f"@{username.lstrip('@')}" if username else f"Telegram ID {payment.user.telegram_user_id}"
    euros, cents = divmod(payment.plan.price_cents, 100)
    amount = f"{euros},{cents:02d} €"
    return "\n".join(
        (
            "💳 Подтверждена оплата",
            f"Пользователь: {recipient}",
            f"Тариф: {i18n.text('ru', f'plan-{payment.plan.code}')}",
            f"Сумма: {amount}",
        )
    )


async def notify_payment_confirmation(payment: ProcessedPayment | None) -> None:
    if payment is None:
        return
    from app.core.i18n import i18n

    if not payment.duplicate:
        if bot is not None:
            await bot.send_message(
                payment.user.telegram_chat_id,
                i18n.text(
                    payment.user.language,
                    "payment-confirmed",
                    plan=i18n.text(payment.user.language, f"plan-{payment.plan.code}"),
                ),
            )
        try:
            await send_operational_notification(settings, operational_payment_confirmation(payment))
        except NotificationBotUnavailable:
            logger.info("operational_payment_notification_skipped", reason="notification_bot_unavailable")
        except Exception:
            logger.exception("operational_payment_notification_failed", user_id=payment.user.id)

    if bot is None:
        return

    async with SessionLocal() as session:
        user = await session.get(User, payment.user.id)
        if user is not None:
            if user.active_navigation_screen == "main":
                await refresh_visible_main_screen(bot, session, user)
            else:
                await main_screen(bot, session, user, NavigationMessageManager())
            await session.commit()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    client = CrousClient(settings)
    try: healthy = await client.health_check()
    finally: await client.close()
    if not healthy: raise HTTPException(503, "CROUS unavailable")
    return {"status": "ok"}


@app.get(settings.payment_success_path)
async def payment_success(session_id: str | None = None) -> HTMLResponse:
    if not session_id:
        return payment_page("Payment could not be verified", "Return to Telegram and try the payment again.", successful=False)
    try:
        checkout = await retrieve_checkout_session(session_id, settings)
        async with SessionLocal() as session:
            payment = await process_paid_checkout(session, checkout, settings)
            await session.commit()
        if payment is None:
            return payment_page("Payment is being verified", "Stripe is still confirming the payment. You can close this page and return to Telegram.", successful=False)
        await notify_payment_confirmation(payment)
    except StripeError:
        return payment_page("Payment is being verified", "Stripe is still confirming the payment. You can close this page and return to Telegram.", successful=False)
    return payment_page("Payment completed", "Your subscription is active. You can close this page and return to the Telegram bot.", successful=True)


@app.get(settings.payment_cancel_path)
async def payment_cancel(user_id: int | None = None, plan_id: int | None = None, token: str | None = None) -> HTMLResponse:
    if user_id is not None and plan_id is not None and token:
        try:
            valid_return = valid_payment_return_token(settings, user_id, plan_id, token)
        except StripeError:
            valid_return = False
    else:
        valid_return = False
    if valid_return and user_id is not None:
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
        if user and bot:
            from app.core.i18n import i18n

            await bot.send_message(user.telegram_chat_id, i18n.text(user.language, "payment-cancelled"))
    return payment_page("Payment was not completed", "No subscription was activated. You can close this page and return to the Telegram bot.", successful=False)


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
    """Process Stripe's signed webhook as an idempotent payment-confirmation path."""
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
        await notify_payment_confirmation(payment)
    except StripeError as error:
        raise HTTPException(400, "Stripe payment could not be processed") from error
    return {"ok": True}
