from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.crous.discovery import Tool, discover_current_tool
from app.crous.exceptions import CrousUnavailable
from app.crous.models import Bounds, CrousListing
from app.crous.parser import parse_detail_page, parse_search_response
from app.searches.service import bounds_log_fields, listing_is_within_bounds, validate_bounds

logger = structlog.get_logger(__name__)


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
        # Validate before discovery/request construction: an invalid area must
        # never be silently converted into an unrestricted national query.
        bounds = validate_bounds(bounds)
        tool = await self.tool()
        body = {"bounds": bounds.as_crous(), "page": page, **(filters or {})}
        endpoint = f"{self.base_url}/api/{self.settings.crous_locale}/search/{tool.id}"
        logger.info(
            "crous_search_request",
            endpoint=endpoint,
            page=page,
            **bounds_log_fields(bounds),
        )
        for attempt in range(3):
            response = await self.client.post(endpoint, json=body)
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt == 2:
                    raise CrousUnavailable(f"CROUS returned {response.status_code}")
                await asyncio.sleep(2**attempt)
                continue
            response.raise_for_status()
            parsed = parse_search_response(response.json(), self.base_url, tool.id)
            accepted = [item for item in parsed if listing_is_within_bounds(item, bounds)]
            logger.info(
                "crous_search_response",
                endpoint=endpoint,
                received_count=len(parsed),
                accepted_count=len(accepted),
                rejected_outside_bounds_count=len(parsed) - len(accepted),
                **bounds_log_fields(bounds),
            )
            return accepted
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
