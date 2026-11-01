from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
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


_TOKEN = "fake-token-for-tests"


def _authed_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SQUAD_API_TOKEN", _TOKEN)
    return _client(_scripted_factory([]))


def test_invocation_is_401_without_or_with_wrong_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _authed_client(monkeypatch)
    assert client.post("/invocations", json={"prompt": "x"}).status_code == 401
    wrong = {"Authorization": "Bearer fake-token-for-other"}
    response = client.post("/invocations", json={"prompt": "x"}, headers=wrong)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_invocation_is_200_with_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _authed_client(monkeypatch)
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    response = client.post("/invocations", json={"prompt": "x"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "complete"


def test_scheme_is_case_insensitive_and_other_schemes_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _authed_client(monkeypatch)
    ok = client.post(
        "/invocations",
        json={"prompt": "x"},
        headers={"Authorization": f"bearer {_TOKEN}"},
    )
    assert ok.status_code == 200
    basic = client.post(
        "/invocations",
        json={"prompt": "x"},
        headers={"Authorization": f"Basic {_TOKEN}"},
    )
    assert basic.status_code == 401


def test_job_status_requires_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _authed_client(monkeypatch)
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    accepted = client.post(
        "/invocations",
        json={"prompt": "review"},
        headers={**headers, "Prefer": "respond-async"},
    )
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]
    assert client.get(f"/jobs/{job_id}").status_code == 401
    assert client.get(f"/jobs/{job_id}", headers=headers).status_code == 200


def test_open_endpoints_stay_open_with_a_token_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEBHOOK_PROVIDERS", "github")
    client = _authed_client(monkeypatch)
    assert client.get("/ping").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/metrics").status_code == 200
    webhook = client.post("/webhooks/github", content=b"{}")
    assert webhook.status_code == 401
    assert webhook.json() == {"detail": "invalid webhook signature"}


def test_unconfigured_token_keeps_endpoints_open_and_warns_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("SQUAD_API_TOKEN", raising=False)
    monkeypatch.delenv("SQUAD_API_TOKEN_FILE", raising=False)
    with caplog.at_level("WARNING", logger="code_squad.server"):
        client = _client(_scripted_factory([]))
    warnings = [r for r in caplog.records if "SQUAD_API_TOKEN" in r.getMessage()]
    assert len(warnings) == 1
    assert client.post("/invocations", json={"prompt": "x"}).status_code == 200


def test_token_file_is_read_at_start_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "api-token"
    token_file.write_text(f"{_TOKEN}\n", encoding="utf-8")
    monkeypatch.delenv("SQUAD_API_TOKEN", raising=False)
    monkeypatch.setenv("SQUAD_API_TOKEN_FILE", str(token_file))
    client = _client(_scripted_factory([]))
    assert client.post("/invocations", json={"prompt": "x"}).status_code == 401
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    assert (
        client.post("/invocations", json={"prompt": "x"}, headers=headers).status_code
        == 200
    )
