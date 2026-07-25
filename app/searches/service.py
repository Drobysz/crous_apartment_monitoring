from __future__ import annotations

import math

from app.crous.models import Bounds


def validate_bounds(bounds: Bounds, max_span: float = 4.0) -> Bounds:
    if not (-180 <= bounds.west < bounds.east <= 180 and -90 <= bounds.south < bounds.north <= 90):
        raise ValueError("Invalid geographic bounds")
    if bounds.east - bounds.west > max_span or bounds.north - bounds.south > max_span:
        raise ValueError("Search area exceeds configured maximum")
    return bounds


def radius_bounds(latitude: float, longitude: float, radius_km: float) -> Bounds:
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or radius_km <= 0:
        raise ValueError("Invalid point or radius")
    latitude_delta = radius_km / 110.574
    longitude_delta = radius_km / (111.320 * max(math.cos(math.radians(latitude)), 0.01))
    return validate_bounds(Bounds(longitude - longitude_delta, latitude + latitude_delta, longitude + longitude_delta, latitude - latitude_delta))


def canonical_zone_key(bounds: Bounds, tool_id: int, filters: dict[str, object] | None = None) -> str:
    import hashlib
    import json
    payload = {"bounds": [round(v, 5) for v in (bounds.west, bounds.north, bounds.east, bounds.south)], "tool": tool_id, "filters": filters or {}}
    return "crous:zone:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
