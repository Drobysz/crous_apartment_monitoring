from dataclasses import dataclass


@dataclass(frozen=True)
class GeocodedPlace:
    display_name: str
    city: str | None
    postal_code: str | None
    country_code: str | None
    latitude: float
    longitude: float
    west: float | None
    north: float | None
    east: float | None
    south: float | None
    provider: str = "photon"
