from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.crous.exceptions import CrousAuthenticationRequired, CrousParseError, CrousUnavailable
from app.crous.models import CrousListing


def normalize_space(value: str | None) -> str | None:
    return re.sub(r"\s+", " ", value or "").strip() or None


def price_from_cents(cents: int | None) -> str | None:
    if cents is None:
        return None
    return f"{cents / 100:,.2f}".replace(",", " ").replace(".", ",") + " €"


def surface_text(minimum: float | None, maximum: float | None) -> str | None:
    if minimum is None:
        return None
    if maximum is None or maximum == minimum:
        return f"{minimum:g} m²"
    return f"de {minimum:g} à {maximum:g} m²"


def parse_price(value: str) -> int | None:
    match = re.search(r"([\d\s]+(?:[,.]\d{1,2})?)\s*€", value)
    if not match:
        return None
    return round(float(match.group(1).replace(" ", "").replace(",", ".")) * 100)


def parse_surface(value: str) -> tuple[float | None, float | None]:
    numbers = [float(item.replace(",", ".")) for item in re.findall(r"\d+(?:[,.]\d+)?", value)]
    return (numbers[0], numbers[-1]) if numbers else (None, None)


def parse_search_response(payload: dict[str, Any], base_url: str, tool_id: int) -> list[CrousListing]:
    results = payload.get("results")
    if not isinstance(results, dict) or not isinstance(results.get("items"), list):
        raise CrousParseError("CROUS response does not have results.items")
    return [parse_listing(item, base_url, tool_id) for item in results["items"] if item.get("available", True)]


def parse_listing(item: dict[str, Any], base_url: str, tool_id: int) -> CrousListing:
    residence = item.get("residence") or {}
    external_id = str(item.get("id") or item.get("code") or "")
    if not external_id or not item.get("label"):
        raise CrousParseError("Listing is missing a stable id or label")
    modes = item.get("occupationModes") or []
    price = next((mode.get("rent", {}).get("min") for mode in modes if mode.get("rent")), None)
    if price is None:
        price = next((mode.get("rent", {}).get("max") for mode in modes if mode.get("rent")), None)
    equipment = [
        label
        for entry in item.get("equipments", [])
        if (label := normalize_space(entry.get("label"))) is not None
    ]
    sanitary = ", ".join(entry for entry in equipment if entry.lower() in {"wc", "douche", "baignoire"}) or None
    kitchen = ", ".join(entry for entry in equipment if any(x in entry.lower() for x in ("frigo", "plaque", "évier", "micro-onde"))) or None
    beds = ", ".join(f"{entry.get('count')} {entry.get('type')}" for entry in item.get("beds", []) if entry.get("count")) or None
    media = item.get("medias") or residence.get("medias") or []
    image = next((entry.get("src") for entry in media if entry.get("src")), None)
    image_url = urljoin(base_url + "/", f"media/{image}") if image else None
    location = residence.get("location") or {}
    return CrousListing(
        external_id=external_id,
        canonical_url=f"{base_url}/tools/{tool_id}/accommodations/{external_id}",
        title=normalize_space(item.get("label")) or external_id,
        residence_name=normalize_space(residence.get("label")),
        address=normalize_space(residence.get("address")),
        latitude=location.get("lat"), longitude=location.get("lon"),
        price_cents=int(price) if price is not None else None,
        price_original=price_from_cents(int(price)) if price is not None else None,
        surface_min=(item.get("area") or {}).get("min"), surface_max=(item.get("area") or {}).get("max"),
        surface_original=surface_text((item.get("area") or {}).get("min"), (item.get("area") or {}).get("max")),
        occupancy_type=", ".join(str(mode.get("type", "")) for mode in modes) or None,
        bed_information=beds, sanitary_information=sanitary, kitchen_information=kitchen,
        equipment=", ".join(equipment) or None, primary_image_url=image_url, raw_payload=item,
    )


def detect_bad_html(html: str) -> None:
    text = HTMLParser(html).text(separator=" ").lower()
    if any(marker in text for marker in ("too many requests", "temporarily unavailable", "service indisponible")):
        raise CrousUnavailable("CROUS overload page")
    if "identification" in text and ("connexion" in text or "connectez-vous" in text):
        raise CrousAuthenticationRequired("CROUS returned an authentication page")


def extract_og_image(html: str, page_url: str) -> str | None:
    document = HTMLParser(html)
    for node in document.css('meta[property="og:image"], meta[name="twitter:image"]'):
        content = node.attributes.get("content")
        if content and not is_invalid_image(content):
            return urljoin(page_url, content)
    return None


def is_invalid_image(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in ("logo", "icon", "sprite", "tracking", ".svg", "pixel"))


def parse_detail_page(html: str, page_url: str) -> dict[str, str | None]:
    detect_bad_html(html)
    document = HTMLParser(html)
    title = document.css_first("h1")
    description = document.css_first("meta[name='description']")
    return {
        "title": normalize_space(title.text()) if title else None,
        "short_description": normalize_space(unescape(description.attributes.get("content") or "")) if description else None,
        "primary_image_url": extract_og_image(html, page_url),
    }
