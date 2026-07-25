from __future__ import annotations

import math
from typing import Any

from app.crous.models import Bounds, CrousListing


class InvalidBounds(ValueError):
    """A geographic area that is unsafe to send to the upstream search API."""


def bounds_log_fields(bounds: Bounds) -> dict[str, float]:
    """Use named fields so logs cannot be confused with another tuple ordering."""
    return {
        "west": bounds.west,
        "south": bounds.south,
        "east": bounds.east,
        "north": bounds.north,
    }


def validate_bounds(bounds: Bounds, max_span: float = 4.0) -> Bounds:
    values = (bounds.west, bounds.north, bounds.east, bounds.south)
    if not all(math.isfinite(value) for value in values):
        raise InvalidBounds("Geographic bounds must contain finite numbers")
    if not (-180 <= bounds.west < bounds.east <= 180 and -90 <= bounds.south < bounds.north <= 90):
        raise InvalidBounds("Invalid geographic bounds")
    if bounds.east - bounds.west > max_span or bounds.north - bounds.south > max_span:
        raise InvalidBounds("Search area exceeds configured maximum")
    return bounds


def bounds_from_serialized(raw: dict[str, Any]) -> Bounds:
    """Read an FSM/geocoder payload without allowing a malformed value through."""
    try:
        bounds = Bounds(
            west=float(raw["west"]),
            north=float(raw["north"]),
            east=float(raw["east"]),
            south=float(raw["south"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidBounds("Geographic bounds are missing or not numeric") from error
    return validate_bounds(bounds)


def radius_bounds(latitude: float, longitude: float, radius_km: float) -> Bounds:
    if not all(math.isfinite(value) for value in (latitude, longitude, radius_km)):
        raise InvalidBounds("Point and radius must be finite")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or radius_km <= 0:
        raise InvalidBounds("Invalid point or radius")
    latitude_delta = radius_km / 110.574
    longitude_delta = radius_km / (111.320 * max(math.cos(math.radians(latitude)), 0.01))
    return validate_bounds(Bounds(longitude - longitude_delta, latitude + latitude_delta, longitude + longitude_delta, latitude - latitude_delta))


def listing_is_within_bounds(listing: CrousListing, bounds: Bounds) -> bool:
    """Reject upstream results outside a search area; unknown locations are unsafe."""
    try:
        latitude = float(listing.latitude)
        longitude = float(listing.longitude)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return False
    return bounds.west <= longitude <= bounds.east and bounds.south <= latitude <= bounds.north


def canonical_zone_key(bounds: Bounds, tool_id: int, filters: dict[str, object] | None = None) -> str:
    import hashlib
    import json
    payload = {"bounds": [round(v, 5) for v in (bounds.west, bounds.north, bounds.east, bounds.south)], "tool": tool_id, "filters": filters or {}}
    return "crous:zone:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
