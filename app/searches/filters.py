from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.core.config import Settings, get_settings
from app.crous.models import CrousListing
from app.db.models import Search


class FilterValidationError(ValueError):
    """A validation failure with a stable code for localized presentation."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


type Bound = Decimal | None
_NUMBER = r"[+-]?(?:\d+(?:[,.]\d+)?|[,.]\d+)"
_RANGE = re.compile(rf"^\s*(?P<minimum>{_NUMBER})\s*(?:-|to|à|до)\s*(?P<maximum>{_NUMBER})\s*$", re.IGNORECASE)
_MINIMUM = re.compile(rf"^\s*(?:>=|≥|min(?:imum)?\s*|from\s*)?(?P<minimum>{_NUMBER})\s*$", re.IGNORECASE)
_MAXIMUM = re.compile(rf"^\s*(?:<=|≤|max(?:imum)?\s*|up\s+to\s*|jusqu(?:’|')?à\s*|до\s*)(?P<maximum>{_NUMBER})\s*$", re.IGNORECASE)


def _decimal(raw: str) -> Decimal:
    try:
        return Decimal(raw.replace(",", "."))
    except InvalidOperation as error:
        raise FilterValidationError("format") from error


def parse_range(value: str, *, maximum: Decimal, currency: bool = False) -> tuple[Bound, Bound]:
    """Parse one or two inclusive bounds without turning omitted values into zero.

    Prices are represented as Decimal only while parsing and converted directly to
    euro cents by ``parse_price_range``. Surface area has one documented unit:
    square metres (m²), represented as a numeric value in the database.
    """
    normalized = (
        value.casefold()
        .replace("m²", "")
        .replace("m2", "")
        .replace("€", "")
        .replace("eur", "")
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .strip()
    )
    range_match = _RANGE.fullmatch(normalized)
    minimum_match = _MINIMUM.fullmatch(normalized)
    maximum_match = _MAXIMUM.fullmatch(normalized)
    minimum: Bound
    maximum_value: Bound
    if range_match:
        minimum = _decimal(range_match.group("minimum"))
        maximum_value = _decimal(range_match.group("maximum"))
    elif maximum_match and normalized.lstrip().startswith(("<", "≤", "max", "up", "jusqu", "до")):
        minimum, maximum_value = None, _decimal(maximum_match.group("maximum"))
    elif minimum_match:
        minimum, maximum_value = _decimal(minimum_match.group("minimum")), None
    else:
        raise FilterValidationError("format")

    if any(bound is not None and bound < 0 for bound in (minimum, maximum_value)):
        raise FilterValidationError("negative")
    if minimum is not None and maximum_value is not None and minimum > maximum_value:
        raise FilterValidationError("min-greater")
    if any(bound is not None and bound > maximum for bound in (minimum, maximum_value)):
        raise FilterValidationError("limit")
    if currency and any(
        bound is not None and (bound * 100) != (bound * 100).to_integral_value()
        for bound in (minimum, maximum_value)
    ):
        raise FilterValidationError("precision")
    return minimum, maximum_value


def parse_price_range(value: str, settings: Settings | None = None) -> tuple[int | None, int | None]:
    settings = settings or get_settings()
    low, high = parse_range(value, maximum=Decimal(str(settings.max_filter_price_euros)), currency=True)
    return (
        int(low * 100) if low is not None else None,
        int(high * 100) if high is not None else None,
    )


def parse_surface_range(value: str, settings: Settings | None = None) -> tuple[float | None, float | None]:
    settings = settings or get_settings()
    low, high = parse_range(value, maximum=Decimal(str(settings.max_filter_surface_m2)))
    return float(low) if low is not None else None, float(high) if high is not None else None


def normalized_format(value: str | None) -> str | None:
    """Map CROUS source values and legacy records to stable, untranslated codes."""
    if not value:
        return None
    normalized = value.casefold()
    if "coloc" in normalized or "shared" in normalized:
        return "colocation"
    if any(item in normalized for item in ("individ", "single", "seul", "alone")):
        return "individual"
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
    search_format = normalized_format(search.accommodation_format)
    if search_format and normalized_format(listing.occupancy_type) != search_format:
        return False
    return True
