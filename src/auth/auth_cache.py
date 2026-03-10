"""In-memory auth cache for proxy key -> provider resolution.

Reduces latency by avoiding a DB round-trip on every request (Helicone uses
KV cache with ~12h TTL). Cache key = raw bearer token; value = auth result.
"""

import time
from typing import Optional

from src.auth.types import ProxyAuthResult


class AuthCache:
    """TTL-based in-memory cache for proxy key auth results."""

    __slots__ = ("_cache", "_expiry", "_ttl", "_max_size", "_order")

    def __init__(self, ttl_seconds: int = 300, max_size: int = 10_000):
        self._cache: dict[str, tuple[ProxyAuthResult, float]] = {}
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._order: list[str] = []  # FIFO eviction

    def get(self, token: str) -> Optional[ProxyAuthResult]:
        """Return cached auth result if present and not expired."""
        now = time.monotonic()
        entry = self._cache.get(token)
        if entry is None:
            return None
        result, expiry = entry
        if now >= expiry:
            self._cache.pop(token, None)
            if token in self._order:
                self._order.remove(token)
            return None
        return result

    def set(self, token: str, result: ProxyAuthResult) -> None:
        """Store auth result for token."""
        if self._max_size <= 0:
            return
        now = time.monotonic()
        while len(self._cache) >= self._max_size and self._order:
            evict = self._order.pop(0)
            self._cache.pop(evict, None)
        self._cache[token] = (result, now + self._ttl)
        if token not in self._order:
            self._order.append(token)

    def invalidate(self, token: str) -> None:
        """Remove one entry (e.g. after key rotation)."""
        self._cache.pop(token, None)
        if token in self._order:
            self._order.remove(token)
