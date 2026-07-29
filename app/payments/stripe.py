from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Purchase, SubscriptionPlan, User
from app.subscriptions.service import activate_subscription, plan_by_code


class StripeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessedPayment:
    user: User
    plan: SubscriptionPlan
    duplicate: bool = False


def _secret(settings: Settings, name: str) -> str:
    value = getattr(settings, name)
    if value is None:
        raise StripeError(f"{name.upper()} is not configured")
    return value.get_secret_value()


async def create_checkout_session(
    session: AsyncSession, user: User, plan_code: str, settings: Settings | None = None
) -> str:
    """Create a Stripe-hosted payment page; card details never reach this app."""
    settings = settings or get_settings()
    plan = await plan_by_code(session, plan_code)
    if plan is None or plan.code in {"free", "trial"} or plan.price_cents <= 0:
        raise StripeError("This plan cannot currently be purchased")
    if not settings.public_base_url:
        raise StripeError("PUBLIC_BASE_URL is not configured")
    base_url = str(settings.public_base_url).rstrip("/")
    payload = {
        "mode": "payment",
        "success_url": f"{base_url}{settings.payment_success_path}?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base_url}{settings.payment_cancel_path}",
        "client_reference_id": str(user.id),
        "line_items[0][price_data][currency]": "eur",
        "line_items[0][price_data][unit_amount]": str(plan.price_cents),
        "line_items[0][price_data][product_data][name]": plan.name,
        "line_items[0][quantity]": "1",
        "metadata[telegram_user_id]": str(user.telegram_user_id),
        "metadata[internal_user_id]": str(user.id),
        "metadata[subscription_id]": str(plan.id),
        "metadata[plan_code]": plan.code,
        "payment_intent_data[metadata][telegram_user_id]": str(user.telegram_user_id),
        "payment_intent_data[metadata][internal_user_id]": str(user.id),
        "payment_intent_data[metadata][subscription_id]": str(plan.id),
        "payment_intent_data[metadata][plan_code]": plan.code,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5)) as client:
        response = await client.post(
            "https://api.stripe.com/v1/checkout/sessions",
            content=urlencode(payload),
            headers={"Authorization": f"Bearer {_secret(settings, 'stripe_secret_key')}", "Content-Type": "application/x-www-form-urlencoded"},
        )
    if not response.is_success:
        raise StripeError("Stripe Checkout could not be created")
    data = response.json()
    url = data.get("url") if isinstance(data, dict) else None
    if not isinstance(url, str) or not url.startswith("https://"):
        raise StripeError("Stripe returned an invalid Checkout URL")
    return url


def verify_webhook(payload: bytes, signature: str | None, secret: str, *, tolerance_seconds: int = 300) -> dict[str, object]:
    """Verify Stripe's signed payload without trusting redirect or Telegram input."""
    if not signature:
        raise StripeError("Missing Stripe signature")
    values: dict[str, list[str]] = {}
    for entry in signature.split(","):
        key, sep, value = entry.partition("=")
        if sep:
            values.setdefault(key, []).append(value)
    try:
        timestamp = int(values["t"][0])
    except (KeyError, ValueError, IndexError) as error:
        raise StripeError("Invalid Stripe signature") from error
    if abs(int(time.time()) - timestamp) > tolerance_seconds:
        raise StripeError("Expired Stripe signature")
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in values.get("v1", [])):
        raise StripeError("Invalid Stripe signature")
    try:
        event = json.loads(payload)
    except json.JSONDecodeError as error:
        raise StripeError("Invalid Stripe event body") from error
    if not isinstance(event, dict):
        raise StripeError("Invalid Stripe event")
    return event


def _metadata(value: object) -> dict[str, str]:
    return {str(key): str(item) for key, item in value.items()} if isinstance(value, dict) else {}


async def process_checkout_completed(
    session: AsyncSession, event: dict[str, object], settings: Settings | None = None
) -> ProcessedPayment | None:
    """Activate only verified, paid Checkout events. Database uniqueness is the idempotency gate."""
    settings = settings or get_settings()
    if event.get("type") != "checkout.session.completed":
        return None
    event_id = event.get("id")
    data = event.get("data")
    checkout = data.get("object") if isinstance(data, dict) else None
    if not isinstance(event_id, str) or not isinstance(checkout, dict):
        raise StripeError("Stripe event is missing identifiers")
    checkout_id = checkout.get("id")
    if not isinstance(checkout_id, str) or checkout.get("payment_status") != "paid":
        return None
    existing = await session.scalar(select(Purchase).where((Purchase.stripe_event_id == event_id) | (Purchase.stripe_checkout_session_id == checkout_id)))
    if existing:
        user = await session.get(User, existing.user_id)
        plan = await session.get(SubscriptionPlan, existing.subscription_plan_id)
        if user is None or plan is None:
            raise StripeError("Existing payment has invalid references")
        return ProcessedPayment(user, plan, duplicate=True)
    metadata = _metadata(checkout.get("metadata"))
    try:
        user_id = int(metadata["internal_user_id"])
        telegram_user_id = int(metadata["telegram_user_id"])
        plan_id = int(metadata["subscription_id"])
        plan_code = metadata["plan_code"]
    except (KeyError, ValueError) as error:
        raise StripeError("Stripe metadata is incomplete") from error
    user = await session.get(User, user_id)
    plan = await session.get(SubscriptionPlan, plan_id)
    if user is None or plan is None or user.telegram_user_id != telegram_user_id or plan.code != plan_code:
        raise StripeError("Stripe metadata does not match a purchasable plan")
    amount_cents = checkout.get("amount_total")
    if (
        checkout.get("client_reference_id") not in (None, str(user.id))
        or checkout.get("currency") not in (None, "eur")
        or not isinstance(amount_cents, int)
        or amount_cents != plan.price_cents
    ):
        raise StripeError("Stripe checkout data did not match the expected customer")
    purchase = Purchase(
        user_id=user.id, subscription_plan_id=plan.id, stripe_checkout_session_id=checkout_id,
        stripe_payment_intent_id=str(checkout["payment_intent"]) if checkout.get("payment_intent") else None,
        stripe_event_id=event_id, amount_cents=amount_cents,
        status="paid", purchased_at=datetime.now(UTC), processed_at=datetime.now(UTC),
    )
    session.add(purchase)
    await session.flush()
    await activate_subscription(session, user, plan, source="stripe", purchase=purchase)
    return ProcessedPayment(user, plan)
