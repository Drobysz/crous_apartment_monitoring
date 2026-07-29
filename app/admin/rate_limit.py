from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic


class LoginRateLimiter:
    """Process-local safety net for login attempts.

    Production deployments keep the API behind the single Nginx proxy, so the
    proxy can additionally apply a shared network rate limit. This limiter is
    deliberately keyed by the proxy-provided client address and never trusts a
    browser-supplied identity field.
    """

    def __init__(self, limit: int = 8, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = monotonic()
        attempts = self._attempts[key]
        while attempts and attempts[0] <= now - self.window_seconds:
            attempts.popleft()
        if len(attempts) >= self.limit:
            return False
        attempts.append(now)
        return True


login_rate_limiter = LoginRateLimiter()
