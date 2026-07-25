from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Search


async def due_search_groups(session: AsyncSession, now: datetime) -> dict[tuple[float, float, float, float], list[Search]]:
    searches = (await session.scalars(select(Search).where(Search.is_active, Search.next_check_at <= now))).all()
    groups: dict[tuple[float, float, float, float], list[Search]] = defaultdict(list)
    for search in searches:
        groups[(search.bounds_west, search.bounds_north, search.bounds_east, search.bounds_south)].append(search)
    return groups
