from __future__ import annotations

import threading
from typing import Any

from fastapi.testclient import TestClient

from code_squad._common.fake_model import ScriptedModel
from code_squad._common.session import InFlightRegistry, MemorySessionStore
from code_squad.server import create_app
from tests.support import finish_turn


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _client(
    calls: list[str],
    services_factory: Any = None,
    store: MemorySessionStore | None = None,
) -> TestClient:
    def _model(model_id: str, *_args: Any) -> ScriptedModel:
        calls.append(model_id)
        return ScriptedModel([finish_turn("comment", "Done.")])

    app = create_app(
        "jim",
        model_factory=_model,
        services_factory=services_factory or (lambda _r, _a: {}),
        session_store=store or MemorySessionStore(),
    )
    return TestClient(app, raise_server_exceptions=False)


def test_repeated_key_returns_the_stored_result_without_rerunning() -> None:
    calls: list[str] = []
    client = _client(calls)
    headers = {"Idempotency-Key": "change-42"}
    first = client.post("/invocations", json={"prompt": "x"}, headers=headers)
    second = client.post("/invocations", json={"prompt": "x"}, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(calls) == 1


def test_body_key_is_honoured_like_the_header() -> None:
    calls: list[str] = []
    client = _client(calls)
    body = {"prompt": "x", "idempotency_key": "body-key"}
    client.post("/invocations", json=body)
    client.post("/invocations", json=body)
    assert len(calls) == 1


def test_key_in_flight_is_409_and_then_replays_the_result() -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def _slow_services(_request: Any, _agent: str) -> dict[str, Any]:
        entered.set()
        release.wait(5)
        return {}

    client = _client(calls, _slow_services)
    headers = {"Idempotency-Key": "in-flight"}
    outcome: dict[str, Any] = {}

    def _first() -> None:
        outcome["response"] = client.post(
            "/invocations", json={"prompt": "x"}, headers=headers
        )

    worker = threading.Thread(target=_first)
    worker.start()
    try:
        assert entered.wait(5)
        busy = client.post("/invocations", json={"prompt": "x"}, headers=headers)
        assert busy.status_code == 409
        assert busy.json() == {"status": "in_flight"}
    finally:
        release.set()
        worker.join(5)
    first = outcome["response"]
    assert first.status_code == 200
    replay = client.post("/invocations", json={"prompt": "x"}, headers=headers)
    assert replay.json() == first.json()
    assert len(calls) == 1


def test_failed_run_releases_the_key_so_a_retry_runs() -> None:
    calls: list[str] = []
    attempts: list[int] = []

    def _flaky_services(_request: Any, _agent: str) -> dict[str, Any]:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("transient")
        return {}

    client = _client(calls, _flaky_services)
    headers = {"Idempotency-Key": "retry-me"}
    failed = client.post("/invocations", json={"prompt": "x"}, headers=headers)
    assert failed.status_code == 500
    retried = client.post("/invocations", json={"prompt": "x"}, headers=headers)
    assert retried.status_code == 200
    assert len(calls) == 1


def test_key_in_body_and_header_must_agree() -> None:
    client = _client([])
    response = client.post(
        "/invocations",
        json={"prompt": "x", "idempotency_key": "a"},
        headers={"Idempotency-Key": "b"},
    )
    assert response.status_code == 422


def test_async_key_replays_the_job_result_after_it_completes() -> None:
    calls: list[str] = []
    client = _client(calls)
    headers = {"Idempotency-Key": "async-1", "Prefer": "respond-async"}
    accepted = client.post("/invocations", json={"prompt": "x"}, headers=headers)
    assert accepted.status_code == 202
    replay = client.post("/invocations", json={"prompt": "x"}, headers=headers)
    assert replay.status_code == 200
    assert replay.json()["status"] == "complete"
    assert len(calls) == 1


def test_registry_acquire_complete_release_and_ttl() -> None:
    clock = _Clock()
    registry = InFlightRegistry(MemorySessionStore(clock=clock), ttl_seconds=60)
    assert registry.try_acquire("k") is True
    assert registry.try_acquire("k") is False
    assert registry.state("k") == {"state": "in_flight"}
    registry.complete("k", {"status_code": 200, "body": {"n": 1}})
    assert registry.state("k") == {
        "state": "done",
        "result": {"status_code": 200, "body": {"n": 1}},
    }
    assert registry.try_acquire("k") is False
    registry.release("k")
    assert registry.state("k") is None
    assert registry.try_acquire("k") is True
    clock.now = 61.0
    assert registry.try_acquire("k") is True
