from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from code_squad._common.fake_model import ScriptedModel, Text, ToolCall, Turn


def _collect(model: ScriptedModel, messages: list[Any]) -> list[dict[str, Any]]:
    async def _run() -> list[dict[str, Any]]:
        return [dict(event) async for event in model.stream(messages)]

    return asyncio.run(_run())


def test_tool_turn_emits_strands_event_sequence() -> None:
    model = ScriptedModel([Turn((ToolCall("finish", {"verdict": "approve"}),))])
    events = _collect(model, [])
    assert events[0] == {"messageStart": {"role": "assistant"}}
    start = events[1]["contentBlockStart"]["start"]["toolUse"]
    assert start["name"] == "finish"
    assert (
        events[2]["contentBlockDelta"]["delta"]["toolUse"]["input"]
        == '{"verdict": "approve"}'
    )
    assert events[3] == {"contentBlockStop": {}}
    assert events[4] == {"messageStop": {"stopReason": "tool_use"}}
    assert events[5]["metadata"]["usage"] == {
        "inputTokens": 10,
        "outputTokens": 5,
        "totalTokens": 15,
    }


def test_text_turn_defaults_to_end_turn_and_max_tokens_is_explicit() -> None:
    model = ScriptedModel(
        [Turn((Text("hi"),)), Turn((Text("cut"),), stop_reason="max_tokens")]
    )
    first = _collect(model, [])
    second = _collect(model, [])
    assert first[1] == {"contentBlockStart": {"start": {}}}
    assert first[2] == {"contentBlockDelta": {"delta": {"text": "hi"}}}
    assert first[4] == {"messageStop": {"stopReason": "end_turn"}}
    assert second[4] == {"messageStop": {"stopReason": "max_tokens"}}


def test_exhausted_script_answers_end_turn_and_calls_are_recorded() -> None:
    model = ScriptedModel([])
    events = _collect(model, [{"role": "user", "content": [{"text": "hello"}]}])
    assert events[2] == {"contentBlockDelta": {"delta": {"text": "script exhausted"}}}
    assert events[4] == {"messageStop": {"stopReason": "end_turn"}}
    [call] = model.calls
    assert call.message_count == 1
    assert call.tool_names == ()


def test_tool_use_ids_are_unique_across_turns() -> None:
    model = ScriptedModel([Turn((ToolCall("a"),)), Turn((ToolCall("b"),))])
    first = _collect(model, [])[1]["contentBlockStart"]["start"]["toolUse"]["toolUseId"]
    second = _collect(model, [])[1]["contentBlockStart"]["start"]["toolUse"][
        "toolUseId"
    ]
    assert first != second


def test_from_json_builds_turns(tmp_path: Path) -> None:
    script = [
        {"tool": "read_knowledge", "input": {"topic": "checklist"}},
        {"text": "done"},
        {"stop_reason": "max_tokens", "text": "partial"},
    ]
    path = tmp_path / "script.json"
    path.write_text(json.dumps(script), encoding="utf-8")
    model = ScriptedModel.from_json(path)
    first = _collect(model, [])
    assert first[4] == {"messageStop": {"stopReason": "tool_use"}}
    _collect(model, [])
    third = _collect(model, [])
    assert third[4] == {"messageStop": {"stopReason": "max_tokens"}}


@pytest.mark.parametrize(
    "script",
    [
        {"text": "not a list"},
        ["not an object"],
        [{"tool": "x", "text": "both"}],
        [{"unknown": 1}],
        [{"text": "x", "stop_reason": "bogus"}],
        [{"tool": "x", "input": "not-a-dict"}],
    ],
)
def test_from_json_rejects_malformed_scripts(tmp_path: Path, script: Any) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(script), encoding="utf-8")
    with pytest.raises(ValueError):
        ScriptedModel.from_json(path)
