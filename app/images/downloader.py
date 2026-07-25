from __future__ import annotations

import hashlib
from dataclasses import dataclass

import httpx

from app.images.validator import validate_image_bytes, validate_image_url


@dataclass(frozen=True)
class DownloadedImage:
    content: bytes
    mime_type: str
    content_hash: str


class SafeImageDownloader:
    def __init__(self, trusted_hosts: set[str], max_bytes: int = 8 * 1024 * 1024) -> None:
        self.trusted_hosts = trusted_hosts
        self.max_bytes = max_bytes

    async def download(self, url: str) -> DownloadedImage:
        validate_image_url(url, self.trusted_hosts)
        async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(20, connect=5)) as client:
            current = url
            for _ in range(3):
                validate_image_url(current, self.trusted_hosts)
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Image redirect has no destination")
                        current = str(response.url.join(location))
                        continue
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self.max_bytes:
                            raise ValueError("Image exceeds maximum size")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    mime = validate_image_bytes(response.headers.get("content-type"), content)
                    return DownloadedImage(content, mime, hashlib.sha256(content).hexdigest())
        raise ValueError("Too many image redirects")
