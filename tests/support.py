from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from typing import Any

from strands import tool

from code_squad._common.common_tools import finish, read_knowledge
from code_squad._common.context import current
from code_squad._common.contract import InvocationRequest
from code_squad._common.fake_model import ScriptedModel, ToolCall, Turn
from code_squad._common.model import ModelFactory
from code_squad._common.registry import get_spec
from code_squad._common.spec import AgentSpec

FAKE_TOKEN = "fake-token-for-tests"


def finding_dict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "agent": "michael",
        "rule_id": "TEST-001",
        "category": "correctness",
        "severity": "major",
        "confidence": "high",
        "file": "src/app.py",
        "line_start": 10,
        "line_end": 12,
        "head_sha": "a" * 40,
        "title": "Off-by-one in loop bound",
        "rationale": "The loop skips the last element.",
    }
    base.update(overrides)
    return base


def finish_turn(
    verdict: str = "approve",
    summary: str = "All good.",
    findings: list[dict[str, Any]] | None = None,
) -> Turn:
    payload: dict[str, Any] = {"verdict": verdict, "summary": summary}
    payload["findings"] = findings if findings is not None else []
    return Turn((ToolCall("finish", payload),))


def make_spec(tools: tuple[Any, ...] | None = None, **overrides: Any) -> AgentSpec:
    base = get_spec("michael")
    chosen: tuple[Any, ...] = tools if tools is not None else (finish, read_knowledge)
    return dataclasses.replace(base, tools=chosen, **overrides)


def request(**overrides: Any) -> InvocationRequest:
    values: dict[str, Any] = {"prompt": "Review the change."}
    values.update(overrides)
    return InvocationRequest.model_validate(values)


def factory_of(*models: ScriptedModel) -> ModelFactory:
    queue = list(models)

    def _factory(*_args: Any) -> ScriptedModel:
        return queue.pop(0)

    return _factory


def recording_factory(models: Sequence[ScriptedModel], log: list[str]) -> ModelFactory:
    queue = list(models)

    def _factory(model_id: str, *_args: Any) -> ScriptedModel:
        log.append(model_id)
        return queue.pop(0)

    return _factory


def publish_test_tool(sink: list[str]) -> Callable[..., str]:
    @tool
    def publish_test(text: str) -> str:
        """Pretend to publish text to an external system (test only)."""
        current().gate.require_write("publish_test")
        sink.append(text)
        return "published"

    return publish_test


def rogue_tool(ran: list[str]) -> Callable[..., str]:
    @tool
    def rogue() -> str:
        """A tool that is deliberately not classified in the policy."""
        ran.append("rogue")
        return "ran"

    return rogue


def tool_result_texts(messages: Sequence[Any]) -> list[str]:
    texts: list[str] = []
    for message in messages:
        for block in message["content"]:
            result = block.get("toolResult")
            if result is None:
                continue
            for item in result["content"]:
                if "text" in item:
                    texts.append(str(item["text"]))
    return texts
