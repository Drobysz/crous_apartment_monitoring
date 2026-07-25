from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.crous.exceptions import CrousParseError


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
        Tool(id=int(value["id"]), management_year=int(value["managementYear"]), mechanism=value["mechanism"])
        for value in data.values()
        if value.get("isEnabled") and value.get("id") is not None
    ]
    if not tools:
        raise CrousParseError("CROUS context did not contain an enabled search tool")
    return tools


async def discover_current_tool(client: httpx.AsyncClient, base_url: str) -> Tool:
    return max(await discover_tools(client, base_url), key=lambda tool: tool.management_year)
