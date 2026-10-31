from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from strands.types.streaming import StreamEvent

from code_squad._common import tool_policy
from code_squad._common.common_tools import finish, read_knowledge
from code_squad._common.contract import InvocationResult, RunStatus, Verdict, finding_id
from code_squad._common.fake_model import ScriptedModel, Text, ToolCall, Turn
from code_squad._common.observability import REGISTRY
from code_squad._common.runtime import run_task
from code_squad._common.tool_policy import ToolClass
from code_squad._common.untrusted import UNTRUSTED_RULE
from tests.support import (
    factory_of,
    finding_dict,
    finish_turn,
    make_spec,
    publish_test_tool,
    recording_factory,
    request,
    rogue_tool,
    tool_result_texts,
)


def _user_text(messages: Any) -> str:
    return str(messages[0]["content"][0]["text"])


def _system(model: ScriptedModel) -> str:
    return model.calls[0].system_prompt or ""


def _dry_run_count(agent: str) -> float:
    return REGISTRY.get_sample_value("squad_dry_run_total", {"agent": agent}) or 0.0


def test_finish_completes_with_findings_and_filled_ids() -> None:
    spec = make_spec()
    finding = finding_dict(head_sha="b" * 40)
    model = ScriptedModel([finish_turn("request_changes", "One issue.", [finding])])
    result = run_task(spec, request(), model_factory=factory_of(model))
    assert result.status is RunStatus.COMPLETE
    assert result.verdict is Verdict.REQUEST_CHANGES
    assert result.summary == "One issue."
    [only] = result.findings
    assert only.id == finding_id("michael", "src/app.py", 10, 12, "TEST-001", "b" * 40)
    assert result.stats.iterations == 1
    assert result.stats.input_tokens == 10
    assert result.stats.output_tokens == 5
    assert result.stats.tool_calls == {"finish": 1}
    assert result.warnings == []


def test_system_prompt_carries_untrusted_rule_and_task_follows_template() -> None:
    model = ScriptedModel([finish_turn()])
    run_task(make_spec(), request(target="42"), model_factory=factory_of(model))
    assert UNTRUSTED_RULE in _system(model)
    first_user = _user_text(model.calls[0].messages)
    assert first_user.startswith("Action: . Project: . Target: 42.")
    assert first_user.endswith("Review the change.")


def test_invalid_finish_is_retried_inside_the_same_run() -> None:
    model = ScriptedModel(
        [
            Turn(
                (
                    ToolCall(
                        "finish", {"verdict": "maybe", "summary": "x", "findings": []}
                    ),
                )
            ),
            finish_turn("comment", "Recovered."),
        ]
    )
    result = run_task(make_spec(), request(), model_factory=factory_of(model))
    assert result.status is RunStatus.COMPLETE
    assert result.summary == "Recovered."
    assert len(model.calls) == 2
    assert any(
        "finish rejected" in text for text in tool_result_texts(model.calls[1].messages)
    )
    assert result.stats.tool_calls == {"finish": 2}


def test_finish_rejected_twice_stops_without_further_model_calls() -> None:
    bad = {"verdict": "maybe", "summary": "x", "findings": []}
    model = ScriptedModel(
        [
            Turn((ToolCall("finish", bad),)),
            Turn((ToolCall("finish", bad),)),
            finish_turn(),
        ]
    )
    result = run_task(make_spec(), request(), model_factory=factory_of(model))
    assert result.status is RunStatus.INCOMPLETE
    assert result.verdict is Verdict.INCOMPLETE
    assert "finish() was rejected twice; no result was produced" in result.warnings
    assert len(model.calls) == 2


def test_iteration_limit_is_incomplete_and_is_not_retried() -> None:
    spec = make_spec(max_iterations=3)
    turns = [
        Turn((ToolCall("read_knowledge", {"topic": "missing"}),)) for _ in range(10)
    ]
    model = ScriptedModel(turns)
    result = run_task(spec, request(), model_factory=factory_of(model))
    assert result.status is RunStatus.INCOMPLETE
    assert result.verdict is Verdict.INCOMPLETE
    assert any("iteration limit reached" in warning for warning in result.warnings)
    assert result.findings == []
    assert len(model.calls) == 3


def test_max_tokens_retries_once_with_shorter_answer_request() -> None:
    log: list[str] = []
    first = ScriptedModel([Turn((Text("partial"),), stop_reason="max_tokens")])
    second = ScriptedModel([finish_turn("approve", "Short.")])
    spec = make_spec(retry_model_id="small-model")
    result = run_task(
        spec, request(), model_factory=recording_factory([first, second], log)
    )
    assert result.status is RunStatus.COMPLETE
    assert result.summary == "Short."
    assert log == [spec.model_id, "small-model"]
    retry_text = _user_text(second.calls[0].messages)
    assert "truncated at the token limit" in retry_text
    assert "Review the change." in retry_text


def test_max_tokens_twice_is_incomplete_without_a_third_attempt() -> None:
    log: list[str] = []
    first = ScriptedModel([Turn((Text("a"),), stop_reason="max_tokens")])
    second = ScriptedModel([Turn((Text("b"),), stop_reason="max_tokens")])
    third = ScriptedModel([finish_turn()])
    result = run_task(
        make_spec(),
        request(),
        model_factory=recording_factory([first, second, third], log),
    )
    assert result.status is RunStatus.INCOMPLETE
    assert len(log) == 2
    assert len(third.calls) == 0


def test_missing_finish_retries_once_then_is_incomplete() -> None:
    first = ScriptedModel([Turn((Text("hello"),))])
    second = ScriptedModel([Turn((Text("still nothing"),))])
    result = run_task(make_spec(), request(), model_factory=factory_of(first, second))
    assert result.status is RunStatus.INCOMPLETE
    assert result.verdict is Verdict.INCOMPLETE
    assert (
        "run ended with stop reason 'end_turn' without finish(); result is incomplete"
        in result.warnings
    )
    assert len(first.calls) == 1
    assert len(second.calls) == 1
    assert "You stopped without calling finish()" in _user_text(
        second.calls[0].messages
    )


def test_missing_finish_retry_can_recover() -> None:
    first = ScriptedModel([Turn((Text("hello"),))])
    second = ScriptedModel([finish_turn("comment", "Recovered after retry.")])
    result = run_task(make_spec(), request(), model_factory=factory_of(first, second))
    assert result.status is RunStatus.COMPLETE
    assert result.summary == "Recovered after retry."


def test_model_exception_yields_failed_without_leaking_content() -> None:
    class _BrokenModel(ScriptedModel):
        async def stream(
            self, *args: Any, **kwargs: Any
        ) -> AsyncGenerator[StreamEvent, None]:
            raise RuntimeError("upstream said: confidential payload")
            yield {}

    result = run_task(
        make_spec(), request(), model_factory=factory_of(_BrokenModel([]))
    )
    assert result.status is RunStatus.FAILED
    assert result.verdict is Verdict.INCOMPLETE
    assert result.warnings == ["model call failed: RuntimeError"]
    assert "confidential" not in result.model_dump_json()


def test_model_factory_error_yields_failed() -> None:
    def _broken_factory(*_args: Any) -> ScriptedModel:
        raise ValueError("LLM_API_KEY or LLM_API_KEY_FILE must be set")

    result = run_task(make_spec(), request(), model_factory=_broken_factory)
    assert result.status is RunStatus.FAILED
    assert result.warnings == ["model call failed: ValueError"]


@pytest.fixture
def publish_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        tool_policy.TOOL_POLICY, "publish_test", ToolClass.EXTERNAL_WRITE
    )


def _publish_run(
    post: bool | None, sink: list[str]
) -> tuple[InvocationResult, ScriptedModel]:
    overrides: dict[str, Any] = {} if post is None else {"post": post}
    spec = make_spec(tools=(finish, read_knowledge, publish_test_tool(sink)))
    model = ScriptedModel(
        [
            Turn((ToolCall("publish_test", {"text": "hi"}),)),
            finish_turn("comment", "Recorded intent."),
        ]
    )
    result = run_task(spec, request(**overrides), model_factory=factory_of(model))
    return result, model


def test_dry_run_blocks_external_write_tool_body(publish_policy: None) -> None:
    sink: list[str] = []
    before = _dry_run_count("michael")
    result, model = _publish_run(False, sink)
    assert sink == []
    assert result.status is RunStatus.COMPLETE
    assert "dry-run blocked 1 external write attempt(s)" in result.warnings
    assert any("dry-run" in text for text in tool_result_texts(model.calls[1].messages))
    assert result.stats.tool_calls["publish_test"] == 1
    assert _dry_run_count("michael") == before + 1
    assert "DRY RUN" in _system(model)


def test_post_true_runs_external_write_tool(publish_policy: None) -> None:
    sink: list[str] = []
    result, model = _publish_run(True, sink)
    assert sink == ["hi"]
    assert result.warnings == []
    assert "External writes are enabled" in _system(model)


def test_absent_post_runs_external_write_tool(publish_policy: None) -> None:
    sink: list[str] = []
    result, _model = _publish_run(None, sink)
    assert sink == ["hi"]
    assert result.warnings == []


def test_unclassified_tool_is_refused_before_it_runs() -> None:
    ran: list[str] = []
    spec = make_spec(tools=(finish, rogue_tool(ran)))
    model = ScriptedModel([Turn((ToolCall("rogue", {}),)), finish_turn()])
    result = run_task(spec, request(), model_factory=factory_of(model))
    assert ran == []
    assert result.status is RunStatus.COMPLETE
    assert any(
        "tool 'rogue' is not classified; refused" in text
        for text in tool_result_texts(model.calls[1].messages)
    )
    assert "rogue" not in result.stats.tool_calls
