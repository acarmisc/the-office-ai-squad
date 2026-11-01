"""Session and job storage.

The default store is in-process memory. Jobs created with ``Prefer: respond-async``
are only visible to the replica that created them, so run a single replica unless
``SESSION_STORE_URL`` points at Redis. The Redis backend needs the optional ``redis``
extra and is not covered by the default test gate.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any, Final, Protocol

_DEFAULT_TTL_SECONDS: Final = 3600


class SessionStore(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...

    def put(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None: ...

    def delete(self, key: str) -> None: ...


class MemorySessionStore:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if self._clock() >= expires_at:
                del self._items[key]
                return None
            return dict(value)

    def put(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        with self._lock:
            self._items[key] = (self._clock() + ttl_seconds, dict(value))

    def delete(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)


class RedisSessionStore:
    def __init__(self, url: str, *, prefix: str = "squad:session:") -> None:
        import redis  # optional dependency, installed with the 'redis' extra

        self._client: Any = redis.Redis.from_url(url)
        self._prefix = prefix

    def get(self, key: str) -> dict[str, Any] | None:
        raw = self._client.get(self._prefix + key)
        if raw is None:
            return None
        loaded: Any = json.loads(raw)
        return loaded if isinstance(loaded, dict) else None

    def put(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self._client.set(
            self._prefix + key, json.dumps(value, default=str), ex=ttl_seconds
        )

    def delete(self, key: str) -> None:
        self._client.delete(self._prefix + key)


class JobStore:
    def __init__(
        self, store: SessionStore, ttl_seconds: int = _DEFAULT_TTL_SECONDS
    ) -> None:
        self._store = store
        self._ttl = ttl_seconds

    def create(self, job_id: str) -> None:
        self.update(job_id, "pending")

    def update(
        self, job_id: str, state: str, result: dict[str, Any] | None = None
    ) -> None:
        entry: dict[str, Any] = {"state": state}
        if result is not None:
            entry["result"] = result
        self._store.put(job_id, entry, self._ttl)

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self._store.get(job_id)
