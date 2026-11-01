from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from code_squad._common.skills.model import RootDiscovery

_Key = tuple[str, str, str]
_DEFAULT_TTL: Final = 600.0


@dataclass(frozen=True)
class _Entry:
    value: RootDiscovery
    expires_at: float


class SkillCache:
    """Discovery results keyed by (project, ref SHA, path), expiring after a TTL."""

    def __init__(
        self,
        ttl_seconds: float = _DEFAULT_TTL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[_Key, _Entry] = {}
        self._lock = threading.Lock()

    def get(self, project: str, ref: str, path: str) -> RootDiscovery | None:
        key: _Key = (project, ref, path)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if self._clock() >= entry.expires_at:
                del self._entries[key]
                return None
            return entry.value

    def put(self, project: str, ref: str, path: str, value: RootDiscovery) -> None:
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            self._entries[(project, ref, path)] = _Entry(value, now + self._ttl)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _purge_expired(self, now: float) -> None:
        expired = [
            key for key, entry in self._entries.items() if now >= entry.expires_at
        ]
        for key in expired:
            del self._entries[key]
