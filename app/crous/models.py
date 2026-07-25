from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Bounds:
    west: float
    north: float
    east: float
    south: float
    def as_crous(self) -> str: return f"{self.west}_{self.north}_{self.east}_{self.south}"


@dataclass
class CrousListing:
    external_id: str
    canonical_url: str
    title: str
    residence_name: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    price_cents: int | None = None
    price_original: str | None = None
    surface_min: float | None = None
    surface_max: float | None = None
    surface_original: str | None = None
    occupancy_type: str | None = None
    bed_information: str | None = None
    sanitary_information: str | None = None
    kitchen_information: str | None = None
    equipment: str | None = None
    primary_image_url: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
