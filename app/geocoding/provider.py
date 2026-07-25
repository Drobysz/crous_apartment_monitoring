from __future__ import annotations

from typing import Any

import httpx

from app.geocoding.base import GeocodingProvider
from app.geocoding.models import GeocodedPlace


class PhotonProvider(GeocodingProvider):
    """CROUS-hosted Photon endpoint with a small, cacheable response surface."""
    def __init__(self, base_url: str = "https://trouverunlogement.lescrous.fr/photon/api") -> None:
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5))

    async def search(self, query: str, locale: str) -> list[GeocodedPlace]:
        response = await self.client.get(self.base_url, params={"q": query[:200], "lang": locale, "limit": 5})
        response.raise_for_status()
        return self._convert(response.json())

    async def reverse(self, latitude: float, longitude: float, locale: str) -> list[GeocodedPlace]:
        response = await self.client.get(self.base_url, params={"lat": latitude, "lon": longitude, "lang": locale, "limit": 5})
        response.raise_for_status()
        return self._convert(response.json())

    def _convert(self, payload: dict[str, Any]) -> list[GeocodedPlace]:
        places: list[GeocodedPlace] = []
        for feature in payload.get("features", []):
            props = feature.get("properties", {})
            lon, lat = feature.get("geometry", {}).get("coordinates", [None, None])
            extent = feature.get("bbox") or [lon, lat, lon, lat]
            if None in (lon, lat) or len(extent) != 4: continue
            city = props.get("city") or props.get("name")
            postcode = props.get("postcode")
            display = f"{city} ({postcode})" if city and postcode else str(city or props.get("name") or "Lieu")
            places.append(GeocodedPlace(display, city, postcode, props.get("countrycode"), lat, lon, extent[0], extent[3], extent[2], extent[1]))
        return places
