from __future__ import annotations

from code_squad._common.session import JobStore, MemorySessionStore


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_memory_store_expires_entries_after_ttl() -> None:
    clock = _Clock()
    store = MemorySessionStore(clock=clock)
    store.put("k", {"v": 1}, ttl_seconds=10)
    clock.now = 9.0
    assert store.get("k") == {"v": 1}
    clock.now = 10.0
    assert store.get("k") is None


def test_memory_store_returns_copies_and_supports_delete() -> None:
    store = MemorySessionStore()
    store.put("k", {"v": 1}, ttl_seconds=60)
    fetched = store.get("k")
    assert fetched is not None
    fetched["v"] = 99
    assert store.get("k") == {"v": 1}
    store.delete("k")
    assert store.get("k") is None


def test_job_store_tracks_state_and_result() -> None:
    jobs = JobStore(MemorySessionStore())
    jobs.create("job-1")
    assert jobs.get("job-1") == {"state": "pending"}
    jobs.update("job-1", "running")
    assert jobs.get("job-1") == {"state": "running"}
    jobs.update("job-1", "done", {"status": "complete"})
    assert jobs.get("job-1") == {"state": "done", "result": {"status": "complete"}}
    assert jobs.get("missing") is None


def test_memory_store_evicts_expired_entries_on_put() -> None:
    clock = _Clock()
    store = MemorySessionStore(clock=clock)
    for index in range(10_000):
        store.put(f"job-{index}", {"state": "done"}, ttl_seconds=10)
    clock.now = 11.0
    store.put("fresh", {"state": "pending"}, ttl_seconds=10)
    assert len(store) == 1
    assert store.get("job-5") is None


def test_memory_store_caps_its_size_and_evicts_least_recently_used() -> None:
    store = MemorySessionStore(max_entries=3)
    for key in ("a", "b", "c"):
        store.put(key, {"v": key}, ttl_seconds=60)
    assert store.get("a") is not None
    store.put("d", {"v": "d"}, ttl_seconds=60)
    assert len(store) == 3
    assert store.get("b") is None
    assert store.get("a") == {"v": "a"}


def test_put_if_absent_is_atomic_and_respects_expiry() -> None:
    clock = _Clock()
    store = MemorySessionStore(clock=clock)
    assert store.put_if_absent("k", {"v": 1}, ttl_seconds=10) is True
    assert store.put_if_absent("k", {"v": 2}, ttl_seconds=10) is False
    assert store.get("k") == {"v": 1}
    clock.now = 10.0
    assert store.put_if_absent("k", {"v": 3}, ttl_seconds=10) is True
