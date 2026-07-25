from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.crous.discovery import Tool, discover_current_tool
from app.crous.exceptions import CrousUnavailable
from app.crous.models import Bounds, CrousListing
from app.crous.parser import parse_detail_page, parse_search_response


class CrousClient:
    """Public CROUS API client; never uses authenticated sessions or bypasses protections."""

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = str(self.settings.crous_base_url).rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8), follow_redirects=False)
        self._tool: Tool | None = None

    async def close(self) -> None:
        await self.client.aclose()

    async def tool(self) -> Tool:
        if self._tool is None:
            self._tool = await discover_current_tool(self.client, self.base_url)
        return self._tool

    async def search(self, bounds: Bounds, filters: dict[str, Any] | None = None, page: int = 0) -> list[CrousListing]:
        tool = await self.tool()
        body = {"bounds": bounds.as_crous(), "page": page, **(filters or {})}
        for attempt in range(3):
            response = await self.client.post(f"{self.base_url}/api/{self.settings.crous_locale}/search/{tool.id}", json=body)
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt == 2:
                    raise CrousUnavailable(f"CROUS returned {response.status_code}")
                await asyncio.sleep(2**attempt)
                continue
            response.raise_for_status()
            return parse_search_response(response.json(), self.base_url, tool.id)
        raise AssertionError("unreachable")

    async def get_listing_details(self, url_or_id: str) -> dict[str, str | None]:
        tool = await self.tool()
        url = url_or_id if url_or_id.startswith("https://") else f"{self.base_url}/tools/{tool.id}/accommodations/{url_or_id}"
        response = await self.client.get(url)
        response.raise_for_status()
        return parse_detail_page(response.text, url)

    async def health_check(self) -> bool:
        response = await self.client.get(f"{self.base_url}/api/health")
        return response.is_success and bool(response.json().get("isSystemOnline"))
