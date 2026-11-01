from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Final

from code_squad._common.observability import CVE_CACHE_HITS

DEFAULT_TTL_SECONDS: Final = 6 * 3600
DEFAULT_MAX_ENTRIES: Final = 10_000


class TtlCache[K, V]:
    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._entries: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def get(self, key: K) -> V | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._entries[key]
            return None
        CVE_CACHE_HITS.inc()
        return value

    def put(self, key: K, value: V) -> None:
        self._entries[key] = (self._clock() + self._ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)
