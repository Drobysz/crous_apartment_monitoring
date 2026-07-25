from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.crous.client import CrousClient
from app.crous.discovery import Tool
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
    assert requests[0].content == b'{"bounds":"6.134292_48.7092349_6.2126188_48.666906","page":0}'


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
