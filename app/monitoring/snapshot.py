from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from urllib.parse import urlsplit, urlunsplit

from app.crous.models import CrousListing


def _text(value: object) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split()) or None


def _url(value: str) -> str:
    parsed = urlsplit(value)
    # CROUS listing identity does not depend on analytics query parameters.
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "")
    )


def listing_identity(item: CrousListing) -> str:
    return item.external_id.strip() or _url(item.canonical_url)


def material_listing(item: CrousListing) -> dict[str, object]:
    """Only fields a user can materially observe in a rendered accommodation card."""
    fields = asdict(item)
    ignored = {"raw_payload", "primary_image_url", "latitude", "longitude"}
    result: dict[str, object] = {}
    for key, value in fields.items():
        if key in ignored:
            continue
        if key == "canonical_url":
            result[key] = _url(str(value))
        elif isinstance(value, str) or value is None:
            result[key] = _text(value)
        else:
            result[key] = value
    return result


def canonical_snapshot(items: list[CrousListing]) -> tuple[list[CrousListing], str]:
    """Deduplicate upstream repeats and derive an order-independent stable hash."""
    unique: dict[str, CrousListing] = {}
    for item in items:
        identity = listing_identity(item)
        previous = unique.get(identity)
        if previous is None or json.dumps(
            material_listing(item), sort_keys=True, ensure_ascii=False
        ) < json.dumps(material_listing(previous), sort_keys=True, ensure_ascii=False):
            unique[identity] = item
    ordered = [unique[key] for key in sorted(unique)]
    payload = [material_listing(item) for item in ordered]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ordered, hashlib.sha256(encoded.encode("utf-8")).hexdigest()
