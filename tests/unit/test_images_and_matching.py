import pytest

from app.images.validator import validate_image_url
from app.searches.matcher import changes_for_snapshot


def test_ssrf_and_non_image_urls_are_rejected() -> None:
    with pytest.raises(ValueError): validate_image_url("http://trouverunlogement.lescrous.fr/a.jpg", {"trouverunlogement.lescrous.fr"})
    with pytest.raises(ValueError): validate_image_url("https://localhost/a.jpg", {"localhost"})


def test_initial_baseline_and_reappearance() -> None:
    assert changes_for_snapshot({}, {1}, initialized=False) == []
    changes = changes_for_snapshot({1: False}, {1, 2}, initialized=True)
    assert {(change.listing_id, change.kind) for change in changes} == {(1, "reappeared"), (2, "new")}
