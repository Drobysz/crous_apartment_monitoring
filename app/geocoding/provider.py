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
    def __init__(
        self,
        base_url: str = "https://trouverunlogement.lescrous.fr/photon/api",
        reverse_url: str = "https://nominatim.openstreetmap.org/reverse",
    ) -> None:
        self.base_url = base_url
        self.reverse_url = reverse_url
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(12, connect=5),
            headers={"User-Agent": "crous-logement-bot/0.1 (reverse-geocoding)"},
        )

    async def search(self, query: str, locale: str) -> list[GeocodedPlace]:
        response = await self.client.get(
            self.base_url,
            params={"q": query[:200], "lang": photon_locale(locale), "limit": 5},
        )
        response.raise_for_status()
        return self._convert(response.json())

    async def reverse(self, latitude: float, longitude: float, locale: str) -> list[GeocodedPlace]:
        # CROUS's hosted Photon route provides forward search only and returns
        # HTTP 400 for lat/lon.  Nominatim is used solely for this reverse
        # lookup and returns a standard GeoJSON feature with a city boundary.
        response = await self.client.get(
            self.reverse_url,
            params={
                "lat": latitude,
                "lon": longitude,
                "format": "geojson",
                "addressdetails": 1,
                "zoom": 10,
                "accept-language": photon_locale(locale),
            },
        )
        response.raise_for_status()
        return self._convert_nominatim(response.json())

    def _convert(self, payload: dict[str, Any]) -> list[GeocodedPlace]:
        places: list[GeocodedPlace] = []
        seen: set[tuple[str, str, str]] = set()
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
            country_code = str(props.get("countrycode") or "").lower()
            if not country_code and str(props.get("country") or "").casefold() == "france":
                country_code = "fr"
            # A geographic name is ambiguous internationally.  Searches are
            # intentionally limited to France, where CROUS operates.
            if country_code != "fr":
                continue
            city = props.get("city") or props.get("name")
            postcode = props.get("postcode")
            identity = (str(city or "").casefold(), str(postcode or ""), country_code)
            if not city or identity in seen:
                continue
            seen.add(identity)
            display = f"{city} ({postcode})" if city and postcode else str(city or props.get("name") or "Lieu")
            places.append(
                GeocodedPlace(
                    display,
                    city,
                    postcode,
                    country_code,
                    lat,
                    lon,
                    extent[0],
                    extent[1],
                    extent[2],
                    extent[3],
                )
            )
        return places

    def _convert_nominatim(self, payload: dict[str, Any]) -> list[GeocodedPlace]:
        places: list[GeocodedPlace] = []
        for feature in payload.get("features", []):
            props = feature.get("properties", {})
            address = props.get("address", {})
            if not isinstance(address, dict) or str(address.get("country_code") or "").lower() != "fr":
                continue
            coordinates = feature.get("geometry", {}).get("coordinates", [None, None])
            bbox = feature.get("bbox")
            if (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or None in coordinates
                or None in bbox
            ):
                continue
            city = next(
                (
                    address.get(key)
                    for key in ("city", "town", "village", "municipality")
                    if address.get(key)
                ),
                None,
            )
            if not city:
                continue
            postcode = address.get("postcode")
            display = f"{city} ({postcode})" if postcode else str(city)
            # Nominatim bbox is west, south, east, north; the application
            # canonical order is west, north, east, south.
            places.append(
                GeocodedPlace(
                    display,
                    str(city),
                    str(postcode) if postcode else None,
                    "fr",
                    float(coordinates[1]),
                    float(coordinates[0]),
                    float(bbox[0]),
                    float(bbox[3]),
                    float(bbox[2]),
                    float(bbox[1]),
                    provider="nominatim",
                )
            )
        return places
