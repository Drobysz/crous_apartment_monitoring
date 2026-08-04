from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.core.i18n import i18n
from app.notifications.gateway import NotificationGateway


class ListingEmbedSource(Protocol):
    title: str
    canonical_url: str
    price_original: str | None
    surface_original: str | None
    address: str | None
    primary_image_url: str | None


def listing_embed_payload(listing: ListingEmbedSource, language: str) -> dict[str, object]:
    """Discord-neutral payload kept within embed and component-size limits."""
    fields = [
        (i18n.text(language, "price", value=listing.price_original or "—"), True),
        (
            i18n.text(language, "surface", value=listing.surface_original or "—"),
            True,
        ),
    ]
    return {
        "title": str(listing.title)[:256],
        "url": str(listing.canonical_url),
        "description": str(listing.address or "")[:4096],
        "image": listing.primary_image_url,
        "fields": fields[:25],
    }


class DiscordNotificationGateway(NotificationGateway):
    """Thin adapter; the live client supplies a channel send coroutine."""

    def __init__(self, send_message: object) -> None:
        self._send_message = send_message

    async def send_favourite_transition(
        self, *, recipient_id: int, language: str, title: str, transition: str
    ) -> None:
        key = "favorite-appeared" if transition == "appeared" else "favorite-disappeared"
        sender = self._send_message
        await sender(recipient_id, i18n.text(language, key, title=title))  # type: ignore[operator]


def report_embed(text: str, created_at: datetime, language: str) -> dict[str, str]:
    return {
        "title": i18n.text(language, "reports"),
        "description": text[:4096],
        "timestamp": created_at.isoformat(),
    }
