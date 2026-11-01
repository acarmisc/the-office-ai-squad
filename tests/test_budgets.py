from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from strands import tool
from strands.types.exceptions import ModelThrottledException

from code_squad._common import policy_hook
from code_squad._common.common_tools import finish
from code_squad._common.config.schema import SquadConfig
from code_squad._common.contract import RunStatus, Verdict
from code_squad._common.fake_model import ScriptedModel, Text, ToolCall, Turn
from code_squad._common.runtime import run_task
from code_squad._common.tool_policy import ToolClass
from code_squad._common.tool_policy import classify as real_classify
from tests.support import factory_of, finish_turn, make_spec, recording_factory, request


def _services(
    *,
    tool_calls: int | None = None,
    wall_clock: int | None = None,
    max_run_tokens: int | None = None,
) -> dict[str, Any]:
    budgets: dict[str, int] = {}
    if tool_calls is not None:
        budgets["tool_calls"] = tool_calls
    if wall_clock is not None:
        budgets["wall_clock_seconds"] = wall_clock
    raw: dict[str, Any] = {"agents": {"michael": {"budgets": budgets}}}
    config = SquadConfig.model_validate(raw)
    limits = SimpleNamespace(max_run_tokens=max_run_tokens) if max_run_tokens else None
    effective_config = SimpleNamespace(agents=config.agents, limits=limits)
    return {"config": SimpleNamespace(config=effective_config)}


def _read(topic: str) -> Turn:
    return Turn((ToolCall("read_knowledge", {"topic": topic}),))


def test_tool_call_budget_stops_the_run_as_incomplete() -> None:
    model = ScriptedModel([_read(f"t{i}") for i in range(5)] + [finish_turn()])
    result = run_task(
        make_spec(),
        request(),
        services=_services(tool_calls=2),
        model_factory=factory_of(model),
    )
    assert result.status is RunStatus.INCOMPLETE
    assert result.verdict is Verdict.INCOMPLETE
    assert any("tool-call budget exhausted" in w for w in result.warnings)
    assert result.stats.tool_calls.get("read_knowledge") == 2


@tool
def _slow() -> str:
    """Sleep briefly (test only)."""
    time.sleep(1.2)
    return "slept"


def test_wall_clock_budget_cancels_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        policy_hook,
        "classify",
        lambda name: ToolClass.READ if name == "_slow" else real_classify(name),
    )
    slow = Turn((ToolCall("_slow", {}),))
    model = ScriptedModel([slow, slow, finish_turn()])
    spec = make_spec(tools=(finish, _slow))
    result = run_task(
        spec,
        request(),
        services=_services(wall_clock=1),
        model_factory=factory_of(model),
    )
    assert result.status is RunStatus.INCOMPLETE
    assert any("wall-clock budget exceeded" in w for w in result.warnings)
    assert result.stats.tool_calls.get("_slow", 0) == 1


def test_run_token_ceiling_stops_retries_and_further_turns() -> None:
    log: list[str] = []
    first = ScriptedModel([Turn((Text("partial"),), stop_reason="max_tokens")])
    second = ScriptedModel([_read("a"), finish_turn()])
    spec = make_spec(retry_model_id="small-model")
    result = run_task(
        spec,
        request(),
        services=_services(max_run_tokens=20),
        model_factory=recording_factory([first, second], log),
    )
    assert result.status is RunStatus.INCOMPLETE
    assert any("token ceiling" in w for w in result.warnings)
    assert len(second.calls) == 1


class _Overloaded(ScriptedModel):
    async def stream(self, *args: Any, **kwargs: Any) -> Any:
        raise _server_error()
        yield  # pragma: no cover


def _bad_request() -> Any:
    return httpx.Response(400, request=httpx.Request("POST", "http://x"))


def _server_error() -> openai.InternalServerError:
    response: Any = httpx.Response(
        500, request=httpx.Request("POST", "http://gateway.test")
    )
    return openai.InternalServerError(
        "gateway overloaded", response=response, body=None
    )


def test_overload_falls_back_once_to_the_configured_model() -> None:
    log: list[str] = []
    primary = _Overloaded([])
    fallback = ScriptedModel([finish_turn("comment", "From fallback.")])
    spec = make_spec(retry_model_id="fallback-model")
    result = run_task(
        spec,
        request(),
        model_factory=recording_factory([primary, fallback], log),
    )
    assert result.status is RunStatus.COMPLETE
    assert result.summary == "From fallback."
    assert log == [spec.model_id, "fallback-model"]
    assert any("fallback model used" in w for w in result.warnings)


def test_client_errors_do_not_trigger_the_fallback() -> None:
    response: Any = httpx.Response(
        400, request=httpx.Request("POST", "http://gateway.test")
    )
    error = openai.BadRequestError("bad", response=response, body=None)

    class _Rejected(ScriptedModel):
        async def stream(self, *args: Any, **kwargs: Any) -> Any:
            raise error
            yield  # pragma: no cover

    log: list[str] = []
    spec = make_spec(retry_model_id="fallback-model")
    result = run_task(
        spec,
        request(),
        model_factory=recording_factory([_Rejected([]), ScriptedModel([])], log),
    )
    assert result.status is RunStatus.FAILED
    assert log == [spec.model_id]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ModelThrottledException("slow down"), True),
        (_server_error(), True),
        (
            openai.BadRequestError(
                "bad",
                response=_bad_request(),
                body=None,
            ),
            False,
        ),
        (ValueError("other"), False),
    ],
)
def test_overload_classification(error: BaseException, expected: bool) -> None:
    from code_squad._common.runtime import _is_overload

    assert _is_overload(error) is expected
