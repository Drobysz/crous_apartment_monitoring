from __future__ import annotations

import re

from app.core.config import Settings, get_settings
from app.crous.models import CrousListing
from app.db.models import Search


class FilterValidationError(ValueError):
    pass


def parse_range(value: str, *, maximum: float, decimal: bool = False) -> tuple[float, float]:
    normalized = value.lower().replace("m²", "").replace("m2", "").replace("€", "")
    numbers = re.findall(r"\d+(?:[,.]\d+)?", normalized)
    if len(numbers) != 2:
        raise FilterValidationError("Enter a minimum and maximum value")
    converted = [float(number.replace(",", ".")) for number in numbers]
    if not decimal and any(item != int(item) for item in converted):
        raise FilterValidationError("Only whole amounts are accepted")
    low, high = converted
    if low < 0 or high < low or high > maximum:
        raise FilterValidationError("The supplied range is outside the allowed limits")
    return low, high


def parse_price_range(value: str, settings: Settings | None = None) -> tuple[int, int]:
    settings = settings or get_settings()
    low, high = parse_range(value, maximum=settings.max_filter_price_euros)
    return int(low * 100), int(high * 100)


def parse_surface_range(value: str, settings: Settings | None = None) -> tuple[float, float]:
    settings = settings or get_settings()
    return parse_range(value, maximum=settings.max_filter_surface_m2, decimal=True)


def normalized_format(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.casefold()
    if "coloc" in normalized or "shared" in normalized:
        return "colocation"
    if any(item in normalized for item in ("individ", "single", "seul")):
        return "individuel"
    return None


def listing_matches_filters(listing: CrousListing, search: Search) -> bool:
    """Missing values are excluded only when the user explicitly requested that comparison."""
    if search.price_min_cents is not None:
        if listing.price_cents is None or listing.price_cents < search.price_min_cents:
            return False
    if search.price_max_cents is not None:
        if listing.price_cents is None or listing.price_cents > search.price_max_cents:
            return False
    surface = listing.surface_max if listing.surface_max is not None else listing.surface_min
    if search.surface_min_m2 is not None:
        if surface is None or surface < search.surface_min_m2:
            return False
    if search.surface_max_m2 is not None:
        if surface is None or surface > search.surface_max_m2:
            return False
    if search.accommodation_format and normalized_format(listing.occupancy_type) != search.accommodation_format:
        return False
    return True
