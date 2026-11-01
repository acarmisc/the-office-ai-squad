from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from code_squad import server
from code_squad._common.config.loader import ConfigSources
from code_squad._common.fake_model import ScriptedModel
from code_squad._common.model import ModelFactory
from code_squad._common.registry import get_spec
from code_squad._common.services import FORCE_DRY_RUN_WARNING, ServiceBuilder
from code_squad._common.session import InFlightRegistry, JobStore, MemorySessionStore
from code_squad.michael.fanout import CircuitBreakers, HttpSpecialistClient
from code_squad.michael.gateway import MichaelWiring, WebhookGateway
from code_squad.server import _run_job, create_app
from tests.support import factory_of, finding_dict, finish_turn, request


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


def test_unconfigured_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SQUAD_API_TOKEN", raising=False)
    monkeypatch.delenv("SQUAD_API_TOKEN_FILE", raising=False)
    monkeypatch.delenv("SQUAD_ALLOW_UNAUTHENTICATED", raising=False)
    client = _client(_scripted_factory([]))
    assert client.post("/invocations", json={"prompt": "x"}).status_code == 401
    assert client.get("/jobs/does-not-exist").status_code == 401
    assert client.get("/ping").status_code == 200


def test_explicit_allow_flag_keeps_endpoints_open_and_warns_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("SQUAD_API_TOKEN", raising=False)
    monkeypatch.delenv("SQUAD_API_TOKEN_FILE", raising=False)
    monkeypatch.setenv("SQUAD_ALLOW_UNAUTHENTICATED", "1")
    with caplog.at_level("WARNING", logger="code_squad.server"):
        client = _client(_scripted_factory([]))
    warnings = [r for r in caplog.records if "SQUAD_API_TOKEN" in r.getMessage()]
    assert len(warnings) == 1
    assert client.post("/invocations", json={"prompt": "x"}).status_code == 200


def test_allow_flag_other_than_one_does_not_open_the_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SQUAD_API_TOKEN", raising=False)
    monkeypatch.delenv("SQUAD_API_TOKEN_FILE", raising=False)
    monkeypatch.setenv("SQUAD_ALLOW_UNAUTHENTICATED", "true")
    client = _client(_scripted_factory([]))
    assert client.post("/invocations", json={"prompt": "x"}).status_code == 401


def test_request_over_the_size_limit_is_413_before_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SQUAD_MAX_REQUEST_BYTES", "200")
    calls: list[str] = []
    client = _client(_scripted_factory(calls))
    big = {"prompt": "x" * 500}
    response = client.post("/invocations", json=big)
    assert response.status_code == 413
    assert calls == []


def test_chunked_body_over_the_size_limit_is_413(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SQUAD_MAX_REQUEST_BYTES", "200")
    calls: list[str] = []
    client = _client(_scripted_factory(calls))
    chunks = [b'{"prompt": "', b"x" * 300, b'"}']
    response = client.post(
        "/invocations",
        content=iter(chunks),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert calls == []


def test_default_size_limit_is_one_megabyte(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SQUAD_MAX_REQUEST_BYTES", raising=False)
    calls: list[str] = []
    client = _client(_scripted_factory(calls))
    response = client.post("/invocations", json={"prompt": "x" * 1_000_100})
    assert response.status_code == 413
    assert calls == []


def test_project_config_org_only_field_is_422_before_any_model_call() -> None:
    calls: list[str] = []
    client = _client(_scripted_factory(calls))
    response = client.post(
        "/invocations",
        json={"prompt": "x", "project_config": {"vcs_provider": "gitlab"}},
    )
    assert response.status_code == 422
    assert any("vcs_provider" in error for error in response.json()["detail"])
    assert calls == []


def _services_with_allowed_models(models: list[str]) -> Any:
    llm = SimpleNamespace(allowed_models=models)
    effective = SimpleNamespace(config=SimpleNamespace(llm=llm))

    def _services(_request: Any, _agent: str) -> dict[str, Any]:
        return {"config": effective}

    return _services


def test_model_outside_the_org_allow_list_is_422_and_never_called() -> None:
    calls: list[str] = []
    app = create_app(
        "jim",
        model_factory=_scripted_factory(calls),
        services_factory=_services_with_allowed_models(["sonnet-5-5"]),
        session_store=MemorySessionStore(),
    )
    client = TestClient(app)
    refused = client.post("/invocations", json={"prompt": "x", "model": "gpt-rogue"})
    assert refused.status_code == 422
    assert calls == []
    allowed = client.post("/invocations", json={"prompt": "x", "model": "sonnet-5-5"})
    assert allowed.status_code == 200
    assert calls == ["sonnet-5-5"]


def test_org_kill_switch_takes_effect_on_the_next_invocation(tmp_path: Path) -> None:
    org_file = tmp_path / "squad.yaml"
    org_file.write_text("posting:\n  force_dry_run: false\n", encoding="utf-8")
    builder = ServiceBuilder(
        config_sources=ConfigSources(
            org_file=org_file, env={}, projects_dir=None, profiles_dir=None
        ),
        env={},
    )
    calls: list[str] = []
    app = create_app(
        "jim",
        model_factory=_scripted_factory(calls),
        services_factory=builder.build,
        session_store=MemorySessionStore(),
    )
    client = TestClient(app)
    first = client.post("/invocations", json={"prompt": "x"}).json()
    assert FORCE_DRY_RUN_WARNING not in first["warnings"]
    org_file.write_text("posting:\n  force_dry_run: true\n", encoding="utf-8")
    second = client.post("/invocations", json={"prompt": "x"}).json()
    assert FORCE_DRY_RUN_WARNING in second["warnings"]


def test_job_failure_logs_exception_type_and_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _boom(*_args: Any) -> Any:
        raise RuntimeError("content that must not be logged")

    jobs = JobStore(MemorySessionStore())
    jobs.create("job-x")
    spec = get_spec("jim")
    with caplog.at_level("ERROR", logger="code_squad.server"):
        _run_job(jobs, "job-x", spec, request(), {}, _scripted_factory([]), None, _boom)
    assert jobs.get("job-x") == {"state": "failed"}
    [record] = [r for r in caplog.records if r.getMessage() == "job failed"]
    assert getattr(record, "error_type", None) == "RuntimeError"
    assert record.exc_info is not None
    assert "content that must not be logged" not in record.getMessage()


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


def test_webhook_gateway_single_flight_shares_the_session_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[WebhookGateway] = []
    real_gateway = WebhookGateway

    def recording_gateway(**kwargs: Any) -> WebhookGateway:
        gateway = real_gateway(**kwargs)
        built.append(gateway)
        return gateway

    monkeypatch.setattr(server, "WebhookGateway", recording_gateway)
    store = MemorySessionStore()
    env = {"WEBHOOK_PROVIDERS": "github", "SQUAD_ALLOW_UNAUTHENTICATED": "1"}
    wiring = MichaelWiring(
        env=env,
        specialist_client=HttpSpecialistClient(
            httpx.Client(), breakers=CircuitBreakers(), env=env
        ),
    )
    create_app("michael", session_store=store, wiring=wiring)
    assert len(built) == 1
    gateway_registry = built[0]._inflight
    assert isinstance(gateway_registry, InFlightRegistry)
    assert gateway_registry.try_acquire("probe")
    assert InFlightRegistry(store).state("probe") is not None
    assert not InFlightRegistry(store).try_acquire("probe")
