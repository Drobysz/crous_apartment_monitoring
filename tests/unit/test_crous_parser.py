import json
from pathlib import Path

import pytest

from app.crous.exceptions import CrousAuthenticationRequired, CrousParseError, CrousUnavailable
from app.crous.parser import detect_bad_html, parse_price, parse_search_response, parse_surface


def test_structured_crous_listing_is_normalized() -> None:
    payload = json.loads((Path(__file__).parents[1] / "fixtures/crous-search.json").read_text())
    listing = parse_search_response(payload, "https://trouverunlogement.lescrous.fr", 47)[0]
    assert listing.external_id == "123"
    assert listing.price_cents == 55210
    assert listing.surface_original == "de 23 à 28 m²"
    assert listing.primary_image_url == "https://trouverunlogement.lescrous.fr/media/123/main.jpg"
    assert listing.kitchen_information == "Evier + plaque, Frigo"


def test_french_numeric_parsing() -> None:
    assert parse_price("552,1 €") == 55210
    assert parse_surface("de 23 à 28 m²") == (23.0, 28.0)


@pytest.mark.parametrize(("html", "exception"), [("<h1>Too many requests</h1>", CrousUnavailable), ("<h1>Identification</h1>Connectez-vous", CrousAuthenticationRequired)])
def test_error_pages_are_not_treated_as_empty_results(html: str, exception: type[Exception]) -> None:
    with pytest.raises(exception): detect_bad_html(html)


def test_malformed_payload_is_not_treated_as_empty_results() -> None:
    with pytest.raises(CrousParseError): parse_search_response({}, "https://example.com", 1)
