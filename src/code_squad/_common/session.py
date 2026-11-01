"""Session, job and idempotency storage.

The default store is in-process memory, bounded by ``max_entries`` (least recently used
entries go first) and purged of expired entries on every write. Jobs created with
``Prefer: respond-async`` are only visible to the replica that created them, so run a
single replica unless ``SESSION_STORE_URL`` points at Redis. The Redis backend needs the
optional ``redis`` extra and is not covered by the default test gate.

``InFlightRegistry`` records single-flight claims (idempotency keys today; the webhook
gateway reuses it for one run per project, change request and head). Its API:

- ``try_acquire(key) -> bool``: claim the key; ``False`` when it is already claimed.
- ``complete(key, result)``: mark the key done and store ``result`` for replays.
- ``release(key)``: drop the claim so a retry can run (call it on failure).
- ``state(key) -> dict | None``: ``{"state": "in_flight"}``, ``{"state": "done",
  "result": ...}`` or ``None`` when the key is free or has expired.

Claims expire after ``ttl_seconds`` so a crashed replica cannot block a key forever.
"""

from __future__ import annotations

import heapq
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, Final, Protocol

_DEFAULT_TTL_SECONDS: Final = 3600
_DEFAULT_MAX_ENTRIES: Final = 10_000
_IN_FLIGHT: Final = "in_flight"
_DONE: Final = "done"


class SessionStore(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...

    def put(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None: ...

    def put_if_absent(
        self, key: str, value: dict[str, Any], ttl_seconds: int
    ) -> bool: ...

    def delete(self, key: str) -> None: ...


class MemorySessionStore:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        *,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._clock = clock
        self._max = max_entries
        self._lock = threading.Lock()
        self._items: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._expiries: list[tuple[float, str]] = []

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if self._clock() >= expires_at:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return dict(value)

    def put(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        with self._lock:
            self._store(key, value, ttl_seconds)

    def put_if_absent(self, key: str, value: dict[str, Any], ttl_seconds: int) -> bool:
        with self._lock:
            self._evict_expired()
            entry = self._items.get(key)
            if entry is not None and self._clock() < entry[0]:
                return False
            self._store(key, value, ttl_seconds)
            return True

    def delete(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def _store(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        now = self._clock()
        self._evict_expired(now)
        expires_at = now + ttl_seconds
        self._items[key] = (expires_at, dict(value))
        self._items.move_to_end(key)
        heapq.heappush(self._expiries, (expires_at, key))
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def _evict_expired(self, now: float | None = None) -> None:
        current = self._clock() if now is None else now
        while self._expiries and self._expiries[0][0] <= current:
            expires_at, key = heapq.heappop(self._expiries)
            entry = self._items.get(key)
            if entry is not None and entry[0] == expires_at:
                del self._items[key]


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

    def put_if_absent(self, key: str, value: dict[str, Any], ttl_seconds: int) -> bool:
        stored = self._client.set(
            self._prefix + key,
            json.dumps(value, default=str),
            ex=ttl_seconds,
            nx=True,
        )
        return bool(stored)

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


class InFlightRegistry:
    def __init__(
        self,
        store: SessionStore,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        *,
        prefix: str = "inflight:",
    ) -> None:
        self._store = store
        self._ttl = ttl_seconds
        self._prefix = prefix

    def try_acquire(self, key: str) -> bool:
        return self._store.put_if_absent(
            self._prefix + key, {"state": _IN_FLIGHT}, self._ttl
        )

    def complete(self, key: str, result: dict[str, Any]) -> None:
        self._store.put(
            self._prefix + key, {"state": _DONE, "result": result}, self._ttl
        )

    def release(self, key: str) -> None:
        self._store.delete(self._prefix + key)

    def state(self, key: str) -> dict[str, Any] | None:
        return self._store.get(self._prefix + key)
