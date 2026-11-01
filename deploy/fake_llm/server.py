"""OpenAI-compatible fake LLM for the offline demo (compose and kind) and tests.

Endpoints: ``POST /v1/chat/completions`` and ``POST /chat/completions`` (streaming
and non-streaming), ``GET /v1/models`` and ``GET /health``.

The stub is stateless. The turn answered is the number of ``assistant`` messages
already in the request, so every new Strands conversation replays its script from
turn 0. The script is chosen by the LiteLLM tag ``agent:<id>`` in ``metadata.tags``
(``extra_body`` is merged into the top-level JSON), falling back to the ``model``
field when it names an agent.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from code_squad._common.fake_model import Text, ToolCall, Turn, load_script
from code_squad._common.registry import AGENT_IDS

SCRIPTS_DIR_ENV: Final = "FAKE_LLM_SCRIPTS_DIR"
DEFAULT_SCRIPTS_DIR: Final = Path(__file__).resolve().parent / "scripts"
_AGENT_TAG_PREFIX: Final = "agent:"
_PROMPT_TOKENS: Final = 10
_COMPLETION_TOKENS: Final = 5
_EXHAUSTED: Final = Turn((Text("script exhausted"),), stop_reason="end_turn")
_FINISH_REASONS: Final[dict[str, str]] = {
    "tool_use": "tool_calls",
    "end_turn": "stop",
    "max_tokens": "length",
}

Scripts = Mapping[str, tuple[Turn, ...]]


@dataclass(frozen=True)
class _Reply:
    text: str | None
    tool_calls: tuple[tuple[str, str, str], ...]
    finish_reason: str


def load_scripts(directory: Path) -> dict[str, tuple[Turn, ...]]:
    scripts: dict[str, tuple[Turn, ...]] = {}
    for agent in AGENT_IDS:
        path = directory / f"{agent}.json"
        if not path.is_file():
            raise FileNotFoundError(f"missing fake-LLM script for {agent}: {path}")
        scripts[agent] = tuple(load_script(path))
    return scripts


def create_app(
    scripts_dir: Path | str | None = None,
    *,
    scripts: Scripts | None = None,
) -> FastAPI:
    loaded: Scripts = scripts or load_scripts(_resolve_dir(scripts_dir))
    app = FastAPI(title="Code Squad fake LLM", version="1")
    app.state.hits = Counter()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        data = [
            {"id": agent, "object": "model", "created": 0, "owned_by": "fake-llm"}
            for agent in sorted(loaded)
        ]
        return {"object": "list", "data": data}

    @app.post("/v1/chat/completions")
    @app.post("/chat/completions")
    async def chat_completions(request: Request) -> Response:
        try:
            body = await request.json()
        except ValueError:
            return _error(400, "request body must be valid JSON", "invalid_json")
        if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
            return _error(400, "request needs a messages list", "invalid_request")
        agent = _agent_for(body, loaded)
        if agent is None:
            return _error(400, "no scripted agent for this request", "unknown_agent")
        turn = _turn_for(loaded[agent], _turn_index(body["messages"]))
        app.state.hits[agent] += 1
        reply = _reply(turn)
        model = str(body.get("model") or agent)
        if body.get("stream") is True:
            include_usage = _include_usage(body)
            return StreamingResponse(
                _sse(model, reply, include_usage), media_type="text/event-stream"
            )
        return JSONResponse(_completion(model, reply))

    return app


def _resolve_dir(scripts_dir: Path | str | None) -> Path:
    if scripts_dir is not None:
        return Path(scripts_dir)
    return Path(os.environ.get(SCRIPTS_DIR_ENV) or DEFAULT_SCRIPTS_DIR)


def _agent_for(body: Mapping[str, Any], scripts: Scripts) -> str | None:
    metadata = body.get("metadata")
    tags = metadata.get("tags") if isinstance(metadata, dict) else None
    for tag in tags if isinstance(tags, list) else []:
        if isinstance(tag, str) and tag.startswith(_AGENT_TAG_PREFIX):
            agent = tag[len(_AGENT_TAG_PREFIX) :]
            if agent in scripts:
                return agent
    model = body.get("model")
    return model if isinstance(model, str) and model in scripts else None


def _turn_index(messages: list[Any]) -> int:
    return sum(
        1
        for message in messages
        if isinstance(message, dict) and message.get("role") == "assistant"
    )


def _turn_for(turns: tuple[Turn, ...], index: int) -> Turn:
    return turns[index] if index < len(turns) else _EXHAUSTED


def _reply(turn: Turn) -> _Reply:
    texts = [item.text for item in turn.items if isinstance(item, Text)]
    calls = [
        (f"call_{uuid.uuid4().hex[:24]}", item.name, json.dumps(item.input))
        for item in turn.items
        if isinstance(item, ToolCall)
    ]
    return _Reply(
        text="".join(texts) or None,
        tool_calls=tuple(calls),
        finish_reason=_FINISH_REASONS[turn.effective_stop_reason()],
    )


def _usage() -> dict[str, int]:
    return {
        "prompt_tokens": _PROMPT_TOKENS,
        "completion_tokens": _COMPLETION_TOKENS,
        "total_tokens": _PROMPT_TOKENS + _COMPLETION_TOKENS,
    }


def _completion(model: str, reply: _Reply) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": reply.text}
    if reply.tool_calls:
        message["tool_calls"] = [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": args},
            }
            for call_id, name, args in reply.tool_calls
        ]
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": reply.finish_reason,
                "logprobs": None,
            }
        ],
        "usage": _usage(),
    }


def _sse(model: str, reply: _Reply, include_usage: bool) -> Iterator[str]:
    base: dict[str, Any] = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
    }
    yield _event({**base, "choices": [_choice({"role": "assistant"}, None)]})
    if reply.text:
        yield _event({**base, "choices": [_choice({"content": reply.text}, None)]})
    for position, (call_id, name, args) in enumerate(reply.tool_calls):
        start = {"index": position, "id": call_id, "type": "function"}
        yield _event(
            {
                **base,
                "choices": [
                    _choice(
                        {
                            "tool_calls": [
                                {**start, "function": {"name": name, "arguments": ""}}
                            ]
                        },
                        None,
                    )
                ],
            }
        )
        yield _event(
            {
                **base,
                "choices": [
                    _choice(
                        {
                            "tool_calls": [
                                {"index": position, "function": {"arguments": args}}
                            ]
                        },
                        None,
                    )
                ],
            }
        )
    yield _event({**base, "choices": [_choice({}, reply.finish_reason)]})
    if include_usage:
        yield _event({**base, "choices": [], "usage": _usage()})
    yield "data: [DONE]\n\n"


def _choice(delta: dict[str, Any], finish_reason: str | None) -> dict[str, Any]:
    return {"index": 0, "delta": delta, "finish_reason": finish_reason}


def _event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _include_usage(body: Mapping[str, Any]) -> bool:
    options = body.get("stream_options")
    return isinstance(options, dict) and options.get("include_usage") is True


def _error(status: int, message: str, code: str) -> JSONResponse:
    body = {
        "error": {"message": message, "type": "invalid_request_error", "code": code}
    }
    return JSONResponse(status_code=status, content=body)
