from dataclasses import dataclass


@dataclass(frozen=True)
class GeocodedPlace:
    display_name: str
    city: str | None
    postal_code: str | None
    country_code: str | None
    latitude: float
    longitude: float
    west: float
    north: float
    east: float
    south: float
    provider: str = "photon"
