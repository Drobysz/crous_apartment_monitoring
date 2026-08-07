from __future__ import annotations

import secrets
from typing import Any, cast


class SearchLock:
    """A short Redis lease, scoped to exactly one saved search."""

    def __init__(self, redis: object, search_id: int, ttl_seconds: int) -> None:
        self.redis = cast(Any, redis)
        self.key = f"crous:search-sync:{search_id}"
        self.token = secrets.token_urlsafe(24)
        self.ttl_seconds = ttl_seconds
        self.acquired = False

    async def __aenter__(self) -> bool:
        self.acquired = bool(
            await self.redis.set(self.key, self.token, nx=True, ex=self.ttl_seconds)
        )
        return self.acquired

    async def __aexit__(self, *_: object) -> None:
        if not self.acquired:
            return
        # Do not delete a lock that has expired and been acquired by another job.
        await self.redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0",
            1,
            self.key,
            self.token,
        )
