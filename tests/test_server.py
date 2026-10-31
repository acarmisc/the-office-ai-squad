from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from code_squad._common.fake_model import ScriptedModel
from code_squad._common.model import ModelFactory
from code_squad._common.session import MemorySessionStore
from code_squad.server import create_app
from tests.support import factory_of, finding_dict, finish_turn


def _client(
    model_factory: ModelFactory | None = None, agent: str = "michael"
) -> TestClient:
    app = create_app(
        agent, model_factory=model_factory, session_store=MemorySessionStore()
    )
    return TestClient(app)


def _scripted_factory(calls: list[str]) -> ModelFactory:
    def _factory(model_id: str, *_args: Any) -> ScriptedModel:
        calls.append(model_id)
        return ScriptedModel(
            [finish_turn("request_changes", "Found one.", [finding_dict()])]
        )

    return _factory


def test_ping_is_ok() -> None:
    response = _client().get("/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_agent() -> None:
    response = _client().get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "agent": "michael"}


def test_ready_is_503_when_agent_cannot_load() -> None:
    response = _client(agent="toby").get("/ready")
    assert response.status_code == 503
    assert response.json()["error"] == "UnknownAgentError"
    assert (
        _client(agent="toby").post("/invocations", json={"prompt": "x"}).status_code
        == 503
    )


def test_invocation_returns_complete_result_and_metrics_are_exposed() -> None:
    client = _client(factory_of(ScriptedModel([finish_turn("comment", "Done.")])))
    response = client.post("/invocations", json={"prompt": "review", "post": False})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["verdict"] == "comment"
    assert body["summary"] == "Done."
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    assert 'squad_invocations_total{agent="michael",status="complete"}' in metrics.text


def test_findings_come_back_with_ids() -> None:
    client = _client(_scripted_factory([]))
    body = client.post("/invocations", json={"prompt": "review"}).json()
    assert body["status"] == "complete"
    assert len(body["findings"]) == 1
    assert len(body["findings"][0]["id"]) == 16


def test_unknown_key_is_422_and_model_is_never_called() -> None:
    calls: list[str] = []
    client = _client(_scripted_factory(calls))
    response = client.post("/invocations", json={"prompt": "x", "bogus": True})
    assert response.status_code == 422
    assert any("bogus" in error for error in response.json()["detail"])
    assert calls == []


def test_foreign_input_key_is_422_with_specific_message() -> None:
    client = _client(_scripted_factory([]))
    response = client.post("/invocations", json={"prompt": "x", "symptom": "pod crash"})
    assert response.status_code == 422
    assert "input key 'symptom' belongs to another agent" in response.json()["detail"]


def test_string_post_is_422() -> None:
    client = _client(_scripted_factory([]))
    response = client.post("/invocations", json={"prompt": "x", "post": "false"})
    assert response.status_code == 422


def test_invalid_json_is_400() -> None:
    client = _client(_scripted_factory([]))
    response = client.post(
        "/invocations",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400


def test_respond_async_returns_202_and_job_completes() -> None:
    client = _client(_scripted_factory([]))
    accepted = client.post(
        "/invocations", json={"prompt": "review"}, headers={"Prefer": "respond-async"}
    )
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]
    body: dict[str, Any] = {}
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        body = client.get(f"/jobs/{job_id}").json()
        if body["state"] in {"done", "failed"}:
            break
        time.sleep(0.01)
    assert body["state"] == "done"
    assert body["result"]["status"] == "complete"


def test_unknown_job_is_404() -> None:
    assert _client().get("/jobs/does-not-exist").status_code == 404
