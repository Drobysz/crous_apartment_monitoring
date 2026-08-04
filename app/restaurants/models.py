from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Restaurant:
    code: int
    name: str
    city: str | None = None
    address: str | None = None
    is_open: bool | None = None
    is_active: bool | None = None
    hours: tuple[str, ...] = ()
    payment_methods: tuple[str, ...] = ()
    transport: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    phone: str | None = None
    email: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RestaurantMenu:
    restaurant_code: int
    date: date
    items: tuple[str, ...]
    state: str = "available"  # available, closed, unavailable, not_published
