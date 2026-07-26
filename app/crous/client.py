from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.crous.discovery import Tool, discover_current_tool
from app.crous.exceptions import CrousParseError, CrousUnavailable
from app.crous.models import Bounds, CrousListing
from app.crous.parser import parse_search_response
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

    async def search(
        self,
        bounds: Bounds,
        filters: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 100,
        correlation_id: str | None = None,
    ) -> list[CrousListing]:
        # Validate before discovery/request construction: an invalid area must
        # never be silently converted into an unrestricted national query.
        bounds = validate_bounds(bounds)
        tool = await self.tool()
        body = {"bounds": bounds.as_crous(), "page": page, "pageSize": page_size, **(filters or {})}
        endpoint = f"{self.base_url}/api/{self.settings.crous_locale}/search/{tool.id}"
        all_items: list[CrousListing] = []
        current_page = page
        total: int | None = None
        raw_count = 0
        logger.info(
            "crous_search_request",
            endpoint=endpoint,
            page=current_page,
            page_size=page_size,
            correlation_id=correlation_id,
            **bounds_log_fields(bounds),
        )
        while True:
            body["page"] = current_page
            payload = await self._post_search(endpoint, body)
            results = payload.get("results")
            if not isinstance(results, dict):
                raise CrousParseError("CROUS response does not have a results object")
            page_items = results.get("items")
            if not isinstance(page_items, list):
                raise CrousParseError("CROUS response does not have results.items")
            parsed = parse_search_response(payload, self.base_url, tool.id)
            all_items.extend(parsed)
            raw_count += len(page_items)
            raw_total = (results.get("total") or {}).get("value")
            if isinstance(raw_total, int | float) and not isinstance(raw_total, bool):
                total = int(raw_total)
            elif isinstance(raw_total, str) and raw_total.isdigit():
                total = int(raw_total)

            # Pagination must be driven by raw records, never by the subset
            # currently available after parsing. A page of unavailable items
            # may legitimately be followed by an available page.
            if total is not None:
                if raw_count >= total:
                    break
                if not page_items:
                    raise CrousUnavailable(
                        f"CROUS returned only {raw_count} of {total} declared results"
                    )
            elif len(page_items) < page_size:
                break
            current_page += 1

        accepted = [item for item in all_items if listing_is_within_bounds(item, bounds)]
        logger.info(
            "crous_search_response",
            endpoint=endpoint,
            raw_result_count=len(all_items),
            parsed_count=len(all_items),
            accepted_count=len(accepted),
            rejected_outside_bounds_count=len(all_items) - len(accepted),
            pages_fetched=current_page - page,
            correlation_id=correlation_id,
            **bounds_log_fields(bounds),
        )
        return accepted

    async def _post_search(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(3):
            response = await self.client.post(endpoint, json=body)
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt == 2:
                    raise CrousUnavailable(f"CROUS returned {response.status_code}")
                await asyncio.sleep(2**attempt)
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise CrousUnavailable("CROUS returned a non-object search payload")
            return payload
        raise AssertionError("unreachable")

    async def health_check(self) -> bool:
        response = await self.client.get(f"{self.base_url}/api/health")
        return response.is_success and bool(response.json().get("isSystemOnline"))
