import pytest

from app.crous.models import Bounds
from app.searches.service import (
    InvalidBounds,
    bounds_from_serialized,
    radius_bounds,
    validate_bounds,
)


def test_radius_is_converted_to_valid_crous_ordered_bounds() -> None:
    bounds = radius_bounds(48.692, 6.184, 5)
    assert bounds.west < 6.184 < bounds.east
    assert bounds.south < 48.692 < bounds.north
    assert len(bounds.as_crous().split("_")) == 4


def test_invalid_bounds_are_rejected() -> None:
    with pytest.raises(ValueError):
        validate_bounds(Bounds(2, 40, 1, 41))


@pytest.mark.parametrize(
    "bounds",
    [
        Bounds(6.134292, 48.7092349, 6.2126188, 48.666906),  # Nancy 54000
        Bounds(5.9581707, 47.2831715, 6.0904785, 47.1927344),  # Besançon 25000
    ],
)
def test_real_city_bounds_are_valid(bounds: Bounds) -> None:
    assert validate_bounds(bounds) is bounds


@pytest.mark.parametrize(
    "raw",
    [
        {"west": 6.18, "north": 48.69, "east": 6.18, "south": 48.69},
        {"west": 6.2, "north": 48.6, "east": 6.1, "south": 48.7},
        {"west": "nan", "north": 48.7, "east": 6.2, "south": 48.6},
        {"west": 6.1, "north": "inf", "east": 6.2, "south": 48.6},
        {"west": 6.1, "north": 48.7, "east": 6.2},
    ],
)
def test_serialized_invalid_bounds_are_rejected(raw: dict[str, object]) -> None:
    with pytest.raises(InvalidBounds):
        bounds_from_serialized(raw)
