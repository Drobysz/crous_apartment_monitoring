from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiogram.enums import ParseMode
from sqlalchemy import BigInteger

from app.bot.cards import send_accommodation_card
from app.crous.models import CrousListing
from app.db.models import User


def test_telegram_identifiers_use_bigint() -> None:
    for name in ("telegram_user_id", "telegram_chat_id", "active_navigation_chat_id"):
        assert isinstance(User.__table__.c[name].type, BigInteger)


@pytest.mark.asyncio
async def test_plain_text_card_uses_html_parse_mode_and_escapes_dynamic_title() -> None:
    calls: list[dict[str, object]] = []

    class FakeBot:
        async def send_message(self, *args: object, **kwargs: object) -> SimpleNamespace:
            kwargs["chat_id"] = args[0]
            kwargs["text"] = args[1]
            calls.append(kwargs)
            return SimpleNamespace(message_id=1)

    listing = CrousListing(
        external_id="test",
        canonical_url="https://example.test/listing",
        title="A & B <studio>",
    )
    await send_accommodation_card(FakeBot(), 6_195_428_170, listing, "ru", datetime.now(UTC))

    assert calls[0]["parse_mode"] == ParseMode.HTML
    assert "A &amp; B &lt;studio&gt;" in str(calls[0]["text"])
