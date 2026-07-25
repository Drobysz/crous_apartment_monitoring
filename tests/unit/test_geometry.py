import pytest

from app.crous.models import Bounds
from app.searches.service import radius_bounds, validate_bounds


def test_radius_is_converted_to_valid_crous_ordered_bounds() -> None:
    bounds = radius_bounds(48.692, 6.184, 5)
    assert bounds.west < 6.184 < bounds.east
    assert bounds.south < 48.692 < bounds.north
    assert len(bounds.as_crous().split("_")) == 4


def test_invalid_bounds_are_rejected() -> None:
    with pytest.raises(ValueError): validate_bounds(Bounds(2, 40, 1, 41))
