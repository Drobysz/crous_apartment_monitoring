from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.crous.client import CrousClient
from app.crous.discovery import Tool
from app.crous.exceptions import CrousUnavailable
from app.crous.models import Bounds
from app.searches.service import InvalidBounds


@pytest.mark.asyncio
async def test_search_sends_fresh_bounds_and_rejects_out_of_area_listings() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": {
                    "items": [
                        {
                            "id": 1,
                            "label": "Nancy room",
                            "residence": {"location": {"lat": 48.69, "lon": 6.18}},
                        },
                        {
                            "id": 2,
                            "label": "Agen room",
                            "residence": {"location": {"lat": 44.2, "lon": 0.62}},
                        },
                    ]
                }
            },
        )

    client = CrousClient(
        Settings(crous_base_url="https://example.test"),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client._tool = Tool(id=47, management_year=2026, mechanism="test")
    bounds = Bounds(6.134292, 48.7092349, 6.2126188, 48.666906)

    try:
        listings = await client.search(bounds)
    finally:
        await client.close()

    assert [listing.external_id for listing in listings] == ["1"]
    assert requests[0].url.path == "/api/fr/search/47"
    assert requests[0].content == (
        b'{"bounds":"6.134292_48.7092349_6.2126188_48.666906","page":1,"pageSize":100}'
    )


@pytest.mark.asyncio
async def test_search_fetches_every_page_before_local_geographic_filtering() -> None:
    pages: list[int] = []

    def listing(identifier: int, latitude: float, longitude: float) -> dict[str, object]:
        return {
            "id": identifier,
            "label": f"Room {identifier}",
            "residence": {"location": {"lat": latitude, "lon": longitude}},
        }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        pages.append(body["page"])
        items = (
            [listing(1, 48.69, 6.18), listing(2, 48.70, 6.19)]
            if body["page"] == 1
            else [listing(3, 48.68, 6.17)]
        )
        return httpx.Response(200, json={"results": {"total": {"value": 3}, "items": items}})

    client = CrousClient(
        Settings(crous_base_url="https://example.test"),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client._tool = Tool(id=47, management_year=2026, mechanism="test")
    try:
        listings = await client.search(Bounds(6.13, 48.72, 6.22, 48.65), page_size=2)
    finally:
        await client.close()

    assert pages == [1, 2]
    assert [listing.external_id for listing in listings] == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_search_does_not_stop_on_an_unavailable_page_before_later_results() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = json.loads(request.content)["page"]
        pages.append(page)
        items = (
            [{"id": 1, "label": "Unavailable", "available": False}]
            if page == 1
            else [{"id": 2, "label": "Available", "residence": {"location": {"lat": 48.69, "lon": 6.18}}}]
        )
        return httpx.Response(200, json={"results": {"total": {"value": 2}, "items": items}})

    client = CrousClient(Settings(crous_base_url="https://example.test"), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    client._tool = Tool(id=47, management_year=2026, mechanism="test")
    try:
        listings = await client.search(Bounds(6.13, 48.72, 6.22, 48.65), page_size=1)
    finally:
        await client.close()
    assert pages == [1, 2]
    assert [listing.external_id for listing in listings] == ["2"]


@pytest.mark.asyncio
async def test_declared_but_missing_page_is_not_mistaken_for_a_smaller_snapshot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = json.loads(request.content)["page"]
        items = [{"id": 1, "label": "Available", "residence": {"location": {"lat": 48.69, "lon": 6.18}}}] if page == 1 else []
        return httpx.Response(200, json={"results": {"total": {"value": 2}, "items": items}})

    client = CrousClient(Settings(crous_base_url="https://example.test"), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    client._tool = Tool(id=47, management_year=2026, mechanism="test")
    try:
        with pytest.raises(CrousUnavailable, match="declared results"):
            await client.search(Bounds(6.13, 48.72, 6.22, 48.65), page_size=1)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invalid_bounds_never_make_an_upstream_request() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = CrousClient(
        Settings(crous_base_url="https://example.test"),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        with pytest.raises(InvalidBounds):
            await client.search(Bounds(6.18, 48.69, 6.18, 48.69))
    finally:
        await client.close()
    assert not called
