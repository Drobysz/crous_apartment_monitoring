from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def validate_image_url(url: str, trusted_hosts: set[str]) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname.lower() not in trusted_hosts
    ):
        raise ValueError("Untrusted image URL")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ValueError("Image hostname cannot be resolved") from error
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Image host resolved to a non-public address")


def validate_image_bytes(content_type: str | None, payload: bytes) -> str:
    mime = (content_type or "").split(";", 1)[0].lower()
    if mime not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Unsupported image MIME type")
    signatures = {
        "image/jpeg": b"\xff\xd8\xff",
        "image/png": b"\x89PNG\r\n\x1a\n",
        "image/webp": b"RIFF",
    }
    if not payload.startswith(signatures[mime]):
        raise ValueError("Response is not a valid image")
    return mime
