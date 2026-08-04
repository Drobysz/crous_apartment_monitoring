from __future__ import annotations

from typing import Protocol


class NotificationGateway(Protocol):
    """Platform adapter boundary; domain code never formats platform payloads."""

    async def send_favourite_transition(
        self, *, recipient_id: int, language: str, title: str, transition: str
    ) -> None: ...
