from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.crous.exceptions import CrousParseError

PUBLIC_SEARCH_MECHANISMS = frozenset({"flow", "residual"})


@dataclass(frozen=True)
class Tool:
    id: int
    management_year: int
    mechanism: str


async def discover_tools(client: httpx.AsyncClient, base_url: str) -> list[Tool]:
    response = await client.get(f"{base_url}/api/global/context")
    response.raise_for_status()
    data = response.json().get("tools", {})
    tools = [
        Tool(
            id=int(value["id"]),
            management_year=int(value["managementYear"]),
            mechanism=value["mechanism"],
        )
        for value in data.values()
        if value.get("isEnabled") and value.get("id") is not None
    ]
    if not tools:
        raise CrousParseError("CROUS context did not contain an enabled search tool")
    return tools


async def discover_current_tool(client: httpx.AsyncClient, base_url: str) -> Tool:
    """Choose the latest public housing-search campaign.

    The context also exposes enabled tools for special workflows, such as direct
    allocation.  Those endpoints do not contain the public listings displayed
    on trouverunlogement and must not be used for a location search.
    """

    public_tools = [
        tool
        for tool in await discover_tools(client, base_url)
        if tool.mechanism in PUBLIC_SEARCH_MECHANISMS
    ]
    if not public_tools:
        raise CrousParseError("CROUS context did not contain an enabled public search tool")

    # Prefer the newest campaign.  When both public mechanisms exist for the
    # same year, the residual campaign is the public availability catalogue.
    return max(
        public_tools,
        key=lambda tool: (tool.management_year, tool.mechanism == "residual", tool.id),
    )
