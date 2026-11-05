"""Per-key rate limiter."""
from __future__ import annotations


class RateLimiter:
    """Allow at most ``limit`` events per key per ``window`` seconds."""

    def __init__(self, limit: int, window: float) -> None:
        if limit < 1 or window <= 0:
            raise ValueError("limit must be >= 1 and window > 0")
        self.limit = limit
        self.window = window
        self._buckets: dict[str, tuple[int, int]] = {}

    def allow(self, key: str, now: float) -> bool:
        bucket = int(now // self.window)
        start, count = self._buckets.get(key, (bucket, 0))
        if start != bucket:
            start, count = bucket, 0
        count += 1
        self._buckets[key] = (start, count)
        return count <= self.limit

    def pending(self, key: str) -> int:
        return self._buckets.get(key, (0, 0))[1]
