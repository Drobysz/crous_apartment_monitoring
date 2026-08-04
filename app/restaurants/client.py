from __future__ import annotations

from datetime import date
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx

from app.restaurants.models import Restaurant, RestaurantMenu


class RestaurantUnavailable(RuntimeError):
    pass


class CrousRestaurantClient:
    """Small defensive adapter for CROUStillant's public, unauthenticated v1 API."""

    base_url = "https://api.croustillant.menu/v1"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(15, connect=6), follow_redirects=False
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def restaurants(self) -> list[Restaurant]:
        data = await self._get("/restaurants")
        rows = data.get("data")
        if not isinstance(rows, list):
            raise RestaurantUnavailable("restaurant API returned no restaurant list")
        return [
            restaurant_from_api(row)
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("code"), int)
        ]

    async def search_city(self, query: str) -> list[Restaurant]:
        needle = query.casefold().strip()
        if not needle:
            return []
        return [
            restaurant
            for restaurant in await self.restaurants()
            if needle
            in " ".join(
                filter(None, (restaurant.name, restaurant.city, restaurant.address))
            ).casefold()
        ]

    async def near(self, latitude: float, longitude: float, *, limit: int = 12) -> list[Restaurant]:
        rows = [
            restaurant
            for restaurant in await self.restaurants()
            if restaurant.latitude is not None and restaurant.longitude is not None
        ]
        return sorted(
            rows,
            key=lambda item: _distance_km(
                latitude, longitude, item.latitude or 0, item.longitude or 0
            ),
        )[:limit]

    async def menu(self, restaurant_code: int, day: date) -> RestaurantMenu:
        # The API has historically exposed the date variant. Accept multiple
        # response shapes so a missing daily publication is not misrepresented.
        try:
            restaurant = next(
                (item for item in await self.restaurants() if item.code == restaurant_code), None
            )
        except RestaurantUnavailable:
            return RestaurantMenu(restaurant_code, day, (), "unavailable")
        if restaurant is not None and restaurant.is_open is False:
            return RestaurantMenu(restaurant_code, day, (), "closed")
        try:
            data = await self._get(
                f"/restaurants/{restaurant_code}/menu/{day.strftime('%d-%m-%Y')}"
            )
        except RestaurantUnavailable as error:
            if "404" in str(error):
                return RestaurantMenu(restaurant_code, day, (), "not_published")
            return RestaurantMenu(restaurant_code, day, (), "unavailable")
        payload = data.get("data")
        if payload is None:
            return RestaurantMenu(restaurant_code, day, (), "not_published")
        items = tuple(_menu_items(payload))
        return RestaurantMenu(
            restaurant_code, day, items, "available" if items else "not_published"
        )

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            response = await self.client.get(f"{self.base_url}{path}")
        except httpx.HTTPError as error:
            raise RestaurantUnavailable("restaurant API is unavailable") from error
        if response.status_code == 404:
            raise RestaurantUnavailable("restaurant API returned 404")
        if response.status_code == 429 or response.status_code >= 500:
            raise RestaurantUnavailable(f"restaurant API returned {response.status_code}")
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RestaurantUnavailable("restaurant API response is invalid") from error
        if not isinstance(payload, dict) or payload.get("success") is False:
            raise RestaurantUnavailable("restaurant API rejected request")
        return payload


def restaurant_from_api(row: dict[str, Any]) -> Restaurant:
    def strings(value: object) -> tuple[str, ...]:
        return (
            tuple(item for item in value if isinstance(item, str) and item.strip())
            if isinstance(value, list)
            else ()
        )

    return Restaurant(
        code=int(row["code"]),
        name=str(row.get("nom") or row["code"]),
        city=row.get("zone") if isinstance(row.get("zone"), str) else None,
        address=row.get("adresse") if isinstance(row.get("adresse"), str) else None,
        is_open=row.get("ouvert") if isinstance(row.get("ouvert"), bool) else None,
        is_active=row.get("actif") if isinstance(row.get("actif"), bool) else None,
        hours=strings(row.get("horaires")),
        payment_methods=strings(row.get("paiement")),
        transport=row.get("acces") if isinstance(row.get("acces"), str) else None,
        latitude=float(row["latitude"]) if isinstance(row.get("latitude"), int | float) else None,
        longitude=float(row["longitude"])
        if isinstance(row.get("longitude"), int | float)
        else None,
        phone=row.get("telephone") if isinstance(row.get("telephone"), str) else None,
        email=row.get("email") if isinstance(row.get("email"), str) else None,
        metadata=row,
    )


def _menu_items(payload: object) -> list[str]:
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, list):
        result: list[str] = []
        for value in payload:
            result.extend(_menu_items(value))
        return result
    if isinstance(payload, dict):
        for key in ("nom", "name", "libelle", "label", "plats", "items", "repas", "menus"):
            if key in payload:
                return _menu_items(payload[key])
    return []


def _distance_km(
    latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float
) -> float:
    lat = radians(latitude_b - latitude_a)
    lon = radians(longitude_b - longitude_a)
    a = sin(lat / 2) ** 2 + cos(radians(latitude_a)) * cos(radians(latitude_b)) * sin(lon / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))
