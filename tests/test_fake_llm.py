"""Fake OpenAI-compatible LLM: protocol shape and end-to-end runs of every agent.

The end-to-end tests serve the stub on a real loopback port and drive the real strands
``OpenAIModel`` (through ``build_model``) with ``run_task``. Nothing leaves the host.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from code_squad._common.contract import InvocationRequest, RunStatus, Verdict
from code_squad._common.model import build_model
from code_squad._common.registry import AGENT_IDS, get_spec
from code_squad._common.runtime import run_task
from deploy.fake_llm.server import create_app, load_scripts

FAKE_KEY = "fake-token-for-tests"
_READY_TIMEOUT_S = 10.0


@pytest.fixture(scope="module")
def stub_server() -> Iterator[tuple[str, FastAPI]]:
    app = create_app()
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_started(server)
    yield f"http://127.0.0.1:{port}", app
    server.should_exit = True
    thread.join(timeout=_READY_TIMEOUT_S)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_started(server: uvicorn.Server) -> None:
    deadline = time.monotonic() + _READY_TIMEOUT_S
    while not server.started:
        if time.monotonic() > deadline:
            raise TimeoutError("fake LLM did not start")
        time.sleep(0.05)


def _chat_body(
    agent: str, messages: list[dict[str, Any]], stream: bool
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "sonnet-5-5",
        "messages": messages,
        "stream": stream,
        "metadata": {"tags": ["squad:code-squad", f"agent:{agent}"]},
    }
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


_USER: list[dict[str, Any]] = [{"role": "user", "content": "smoke test"}]
_ONE_TURN: list[dict[str, Any]] = [*_USER, {"role": "assistant", "content": None}]


@pytest.mark.parametrize("agent", AGENT_IDS)
def test_default_scripts_call_read_knowledge_then_finish(agent: str) -> None:
    client = TestClient(create_app())
    first = client.post("/v1/chat/completions", json=_chat_body(agent, _USER, False))
    second = client.post(
        "/v1/chat/completions", json=_chat_body(agent, _ONE_TURN, False)
    )
    first_call = first.json()["choices"][0]["message"]["tool_calls"][0]["function"]
    second_choice = second.json()["choices"][0]
    assert first_call["name"] == "read_knowledge"
    assert second_choice["finish_reason"] == "tool_calls"
    assert second_choice["message"]["tool_calls"][0]["function"]["name"] == "finish"


def test_streaming_shape_matches_openai_chunks() -> None:
    client = TestClient(create_app())
    response = client.post("/v1/chat/completions", json=_chat_body("jim", _USER, True))
    assert response.headers["content-type"].startswith("text/event-stream")
    lines = [line for line in response.text.split("\n\n") if line.strip()]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(line.removeprefix("data: ")) for line in lines[:-1]]
    assert all(chunk["object"] == "chat.completion.chunk" for chunk in chunks)
    tool_starts = [
        call
        for chunk in chunks
        for choice in chunk["choices"]
        for call in choice["delta"].get("tool_calls", [])
        if "id" in call
    ]
    assert tool_starts[0]["function"]["name"] == "read_knowledge"
    assert tool_starts[0]["index"] == 0
    finish_chunk = chunks[-2]
    assert finish_chunk["choices"][0]["finish_reason"] == "tool_calls"
    assert chunks[-1]["choices"] == []
    assert chunks[-1]["usage"]["total_tokens"] > 0


def test_turn_index_is_stateless_and_counts_assistant_messages() -> None:
    client = TestClient(create_app())
    messages = [
        *_USER,
        {"role": "assistant", "content": None},
        {"role": "tool", "tool_call_id": "x", "content": "ok"},
        {"role": "assistant", "content": None},
    ]
    response = client.post(
        "/v1/chat/completions", json=_chat_body("jim", messages, False)
    )
    assert response.json()["choices"][0]["finish_reason"] == "stop"
    assert "script exhausted" in response.json()["choices"][0]["message"]["content"]


def _first_topic(response: Any) -> str:
    call = response.json()["choices"][0]["message"]["tool_calls"][0]["function"]
    topic: str = json.loads(call["arguments"])["topic"]
    return topic


def test_agent_is_selected_by_tag_then_by_model_name() -> None:
    client = TestClient(create_app())
    by_tag = client.post(
        "/chat/completions",
        json={
            "model": "sonnet-5-5",
            "messages": _USER,
            "stream": False,
            "metadata": {"tags": ["agent:angela"]},
        },
    )
    by_model = client.post(
        "/chat/completions",
        json={"model": "dwight", "messages": _USER, "stream": False},
    )
    assert _first_topic(by_tag) == "java/index"
    assert _first_topic(by_model) == "security/index"


def test_unknown_agent_is_a_client_error() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/v1/chat/completions",
        json={"model": "sonnet-5-5", "messages": _USER, "stream": False},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_agent"


def test_health_and_models_endpoints() -> None:
    client = TestClient(create_app())
    assert client.get("/health").json() == {"status": "ok"}
    model_ids = {item["id"] for item in client.get("/v1/models").json()["data"]}
    assert model_ids == set(AGENT_IDS)


def test_scripts_directory_is_overridable(tmp_path: Path) -> None:
    for agent in AGENT_IDS:
        script = [{"text": f"custom {agent}"}]
        (tmp_path / f"{agent}.json").write_text(json.dumps(script), encoding="utf-8")
    client = TestClient(create_app(tmp_path))
    body = client.post("/v1/chat/completions", json=_chat_body("pam", _USER, False))
    assert body.json()["choices"][0]["message"]["content"] == "custom pam"


def test_missing_script_fails_at_startup(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="michael"):
        load_scripts(tmp_path)


@pytest.mark.parametrize("agent", AGENT_IDS)
def test_every_agent_completes_through_the_real_openai_model(
    agent: str,
    stub_server: tuple[str, FastAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url, app = stub_server
    monkeypatch.setenv("LLM_BASE_URL", base_url)
    monkeypatch.setenv("LLM_API_KEY", FAKE_KEY)
    request = InvocationRequest.model_validate({"prompt": "smoke test", "post": False})

    result = run_task(
        get_spec(agent), request, model_factory=build_model, post_override=False
    )

    assert result.agent == agent
    assert result.status is RunStatus.COMPLETE, result.warnings
    assert result.verdict is Verdict.COMMENT
    assert result.findings == []
    assert result.posted.notes == 0
    assert result.posted.discussions == 0
    assert result.stats.tool_calls["read_knowledge"] == 1
    assert result.stats.tool_calls["finish"] == 1
    assert app.state.hits[agent] >= 2
