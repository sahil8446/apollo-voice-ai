"""Tiny in-process TTL cache for read-heavy, rarely-changing data.

Doctors and departments are read on almost every call but change maybe once a
month. Caching them removes that DB load from the hot path. The interface is
deliberately minimal so the backend can be swapped for Redis at scale without
touching call sites — only this module changes.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import get_settings

settings = get_settings()


class TTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()
        # monotonic() is injected to stay testable and avoid wall-clock skew.
        self._now: Callable[[], float] = time.monotonic

    async def get_or_set(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
        *,
        cache_empty: bool = True,
    ) -> Any:
        """Return a cached value or load and cache it.

        ``cache_empty=False`` means a falsy result (e.g. an empty list because
        the DB wasn't seeded yet) is NOT cached, so the next call retries
        instead of serving stale emptiness for the whole TTL window.
        """
        now = self._now()
        cached = self._store.get(key)
        if cached and cached[0] > now:
            return cached[1]

        # Serialize concurrent misses so the loader runs once (no stampede).
        async with self._lock:
            cached = self._store.get(key)
            if cached and cached[0] > self._now():
                return cached[1]
            value = await loader()
            if cache_empty or value:
                self._store[key] = (self._now() + self._ttl, value)
            return value

    def invalidate(self, key: str | None = None) -> None:
        """Drop one key (after a write) or the whole cache."""
        if key is None:
            self._store.clear()
        else:
            self._store.pop(key, None)


cache = TTLCache(ttl_seconds=settings.cache_ttl_seconds)
