from __future__ import annotations

from typing import Any

import httpx

from app.geocoding.base import GeocodingProvider
from app.geocoding.models import GeocodedPlace


def photon_locale(locale: str) -> str:
    """Photon currently supports French and English only; UI language is independent."""
    return locale if locale in {"fr", "en"} else "fr"


class PhotonProvider(GeocodingProvider):
    """CROUS-hosted Photon endpoint with a small, cacheable response surface."""
    def __init__(self, base_url: str = "https://trouverunlogement.lescrous.fr/photon/api") -> None:
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5))

    async def search(self, query: str, locale: str) -> list[GeocodedPlace]:
        response = await self.client.get(
            self.base_url,
            params={"q": query[:200], "lang": photon_locale(locale), "limit": 5},
        )
        response.raise_for_status()
        return self._convert(response.json())

    async def reverse(self, latitude: float, longitude: float, locale: str) -> list[GeocodedPlace]:
        response = await self.client.get(
            self.base_url,
            params={
                "lat": latitude,
                "lon": longitude,
                "lang": photon_locale(locale),
                "limit": 5,
            },
        )
        response.raise_for_status()
        return self._convert(response.json())

    def _convert(self, payload: dict[str, Any]) -> list[GeocodedPlace]:
        places: list[GeocodedPlace] = []
        for feature in payload.get("features", []):
            props = feature.get("properties", {})
            lon, lat = feature.get("geometry", {}).get("coordinates", [None, None])
            # Photon puts the bounding box in properties.extent, ordered as
            # west, north, east, south.  GeoJSON's optional bbox is absent on
            # this endpoint, so using the point as a fallback creates a zero
            # area and must never be offered as an "entire city" search.
            extent = props.get("extent")
            if None in (lon, lat):
                continue
            if not isinstance(extent, list) or len(extent) != 4:
                extent = [None, None, None, None]
            city = props.get("city") or props.get("name")
            postcode = props.get("postcode")
            display = f"{city} ({postcode})" if city and postcode else str(city or props.get("name") or "Lieu")
            places.append(
                GeocodedPlace(
                    display,
                    city,
                    postcode,
                    props.get("countrycode"),
                    lat,
                    lon,
                    extent[0],
                    extent[1],
                    extent[2],
                    extent[3],
                )
            )
        return places
