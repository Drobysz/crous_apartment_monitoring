import json
from pathlib import Path

import pytest

from app.crous.exceptions import CrousParseError
from app.crous.parser import parse_price, parse_search_response, parse_surface, preview_image_url


def test_structured_crous_listing_is_normalized() -> None:
    payload = json.loads((Path(__file__).parents[1] / "fixtures/crous-search.json").read_text())
    listing = parse_search_response(payload, "https://trouverunlogement.lescrous.fr", 47)[0]
    assert listing.external_id == "123"
    assert listing.price_cents == 55210
    assert listing.surface_original == "de 23 à 28 m²"
    assert (
        listing.primary_image_url
        == "https://trouverunlogement.lescrous.fr/media/cache/resolve/preview/123/main.jpg"
    )
    assert listing.kitchen_information == "Evier + plaque, Frigo"


def test_french_numeric_parsing() -> None:
    assert parse_price("552,1 €") == 55210
    assert parse_surface("de 23 à 28 m²") == (23.0, 28.0)


def test_preview_image_url_encodes_media_filename_without_changing_key_path() -> None:
    assert preview_image_url(
        "https://trouverunlogement.lescrous.fr",
        "2789/6271376c8b7e2-SDB CH 14M².jpg",
    ) == (
        "https://trouverunlogement.lescrous.fr/"
        "media/cache/resolve/preview/2789/6271376c8b7e2-SDB%20CH%2014M%C2%B2.jpg"
    )


def test_malformed_payload_is_not_treated_as_empty_results() -> None:
    with pytest.raises(CrousParseError): parse_search_response({}, "https://example.com", 1)


def test_unavailable_json_records_are_excluded_without_html_fallback() -> None:
    payload = {"results": {"items": [{"id": 1, "label": "Unavailable", "available": False}]}}
    assert parse_search_response(payload, "https://example.com", 1) == []
