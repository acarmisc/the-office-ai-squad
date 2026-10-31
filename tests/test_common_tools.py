from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, cast

import pytest
from strands.types.tools import ToolContext

from code_squad._common.common_tools import MAX_INVALID_FINISH, finish, read_knowledge
from code_squad._common.context import InvocationContext, current, use_context
from code_squad._common.posting import PostingGate
from tests.support import finding_dict, request


@dataclass
class _FakeAgent:
    cancelled: list[dict[str, Any]] = field(default_factory=list)

    def cancel(self, **kwargs: Any) -> None:
        self.cancelled.append(kwargs)


def _context(agent: str = "michael") -> InvocationContext:
    req = request()
    return InvocationContext(
        agent=agent, request=req, gate=PostingGate.from_request(req)
    )


def _tool_context(fake: _FakeAgent) -> ToolContext:
    return ToolContext(
        tool_use={"toolUseId": "t1", "name": "finish", "input": {}},
        agent=cast(Any, fake),
        invocation_state={},
    )


def test_current_raises_outside_an_invocation() -> None:
    with pytest.raises(RuntimeError):
        current()


def test_use_context_sets_and_resets() -> None:
    ctx = _context()
    with use_context(ctx) as active:
        assert current() is active
    with pytest.raises(RuntimeError):
        current()


def test_valid_finish_stores_payload_and_cancels_loop() -> None:
    ctx = _context()
    fake = _FakeAgent()
    with use_context(ctx):
        reply = finish(
            verdict="approve",
            summary="fine",
            findings=[finding_dict()],
            tool_context=_tool_context(fake),
        )
    assert reply == "finish accepted"
    assert ctx.finish_result is not None
    assert ctx.finish_result.summary == "fine"
    assert fake.cancelled == [{"after_current_tools": True}]


def test_invalid_finish_returns_error_text_without_cancelling() -> None:
    ctx = _context()
    fake = _FakeAgent()
    with use_context(ctx):
        reply = finish(
            verdict="maybe",
            summary="x",
            findings=[],
            tool_context=_tool_context(fake),
        )
    assert reply.startswith("finish rejected")
    assert "verdict" in reply
    assert ctx.finish_result is None
    assert ctx.invalid_finish_attempts == 1
    assert fake.cancelled == []


def test_finish_stops_the_run_after_repeated_invalid_calls() -> None:
    ctx = _context()
    fake = _FakeAgent()
    with use_context(ctx):
        for _ in range(MAX_INVALID_FINISH):
            finish(
                verdict="bad",
                summary="x",
                findings=[],
                tool_context=_tool_context(fake),
            )
    assert ctx.invalid_finish_attempts == MAX_INVALID_FINISH
    assert fake.cancelled == [{"after_current_tools": True}]


def test_read_knowledge_rejects_traversal_and_absolute_topics() -> None:
    with use_context(_context()):
        assert read_knowledge(topic="../secrets") == "invalid topic name"
        assert read_knowledge(topic="/etc/passwd") == "invalid topic name"
        assert read_knowledge(topic="a/../b") == "invalid topic name"
        assert read_knowledge(topic="Upper") == "invalid topic name"


def test_read_knowledge_reads_topics_and_lists_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    knowledge = tmp_path / "knowledge"
    (knowledge / "react").mkdir(parents=True)
    (knowledge / "checklist.md").write_text("# Checklist\n", encoding="utf-8")
    (knowledge / "README.md").write_text("readme", encoding="utf-8")
    (knowledge / "react" / "hooks.md").write_text("# Hooks\n", encoding="utf-8")
    monkeypatch.setattr(resources, "files", lambda _package: tmp_path)
    with use_context(_context()):
        assert read_knowledge(topic="checklist") == "# Checklist\n"
        assert read_knowledge(topic="react/hooks") == "# Hooks\n"
        missing = read_knowledge(topic="missing")
    assert "not found" in missing
    assert "checklist" in missing
    assert "README" not in missing


def test_read_knowledge_lists_none_when_pack_is_empty() -> None:
    with use_context(_context("michael")):
        reply = read_knowledge(topic="does-not-exist")
    assert "available topics: none" in reply
