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
