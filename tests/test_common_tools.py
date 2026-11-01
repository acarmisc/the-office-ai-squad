from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest
from strands.types.tools import ToolContext

from code_squad._common import common_tools
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


def _packs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    packs = {
        "code_squad.michael": tmp_path / "agent",
        "code_squad._common": tmp_path / "shared",
    }

    def _fake_package(package: str) -> Path | None:
        root = packs.get(package)
        return None if root is None else root / "knowledge"

    monkeypatch.setattr(common_tools, "_package_knowledge", _fake_package)
    return packs


def test_read_knowledge_rejects_traversal_and_absolute_topics() -> None:
    with use_context(_context()):
        assert read_knowledge(topic="../secrets") == "invalid topic name"
        assert read_knowledge(topic="/etc/passwd") == "invalid topic name"
        assert read_knowledge(topic="a/../b") == "invalid topic name"
        assert read_knowledge(topic="a//b") == "invalid topic name"
        assert read_knowledge(topic="Upper") == "invalid topic name"


def test_read_knowledge_reads_nested_topics_and_index_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packs = _packs(monkeypatch, tmp_path)
    agent = packs["code_squad.michael"] / "knowledge"
    (agent / "react").mkdir(parents=True)
    (agent / "checklist.md").write_text("# Checklist\n", encoding="utf-8")
    (agent / "README.md").write_text("readme", encoding="utf-8")
    (agent / "react" / "index.md").write_text("# Index\n", encoding="utf-8")
    (agent / "react" / "hooks.md").write_text("# Hooks\n", encoding="utf-8")
    with use_context(_context()):
        assert read_knowledge(topic="checklist") == "# Checklist\n"
        assert read_knowledge(topic="react/hooks") == "# Hooks\n"
        assert read_knowledge(topic="react/index") == "# Index\n"
        missing = read_knowledge(topic="missing")
    assert "not found" in missing
    assert "checklist, react/hooks, react/index" in missing
    assert "README" not in missing


def test_agent_pack_wins_and_shared_pack_is_the_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packs = _packs(monkeypatch, tmp_path)
    (packs["code_squad._common"] / "knowledge" / "react").mkdir(parents=True)
    (packs["code_squad._common"] / "knowledge" / "react" / "hooks.md").write_text(
        "shared hooks", encoding="utf-8"
    )
    (packs["code_squad.michael"] / "knowledge" / "react").mkdir(parents=True)
    (packs["code_squad.michael"] / "knowledge" / "react" / "hooks.md").write_text(
        "agent hooks", encoding="utf-8"
    )
    (packs["code_squad._common"] / "knowledge" / "shared-only.md").write_text(
        "shared only", encoding="utf-8"
    )
    with use_context(_context()):
        assert read_knowledge(topic="react/hooks") == "agent hooks"
        assert read_knowledge(topic="shared-only") == "shared only"


def test_extra_dirs_from_services_are_searched_last(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _packs(monkeypatch, tmp_path)
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "house-rules.md").write_text("house rules", encoding="utf-8")
    ctx = _context()
    ctx.services["knowledge_extra_dirs"] = [str(extra), "relative/dir", "/nope"]
    with use_context(ctx):
        assert read_knowledge(topic="house-rules") == "house rules"
        assert "house-rules" in read_knowledge(topic="unknown")


def test_symlink_escaping_its_pack_is_not_readable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packs = _packs(monkeypatch, tmp_path)
    secret = tmp_path / "outside.md"
    secret.write_text("outside the pack", encoding="utf-8")
    agent = packs["code_squad.michael"] / "knowledge"
    agent.mkdir(parents=True)
    (agent / "link.md").symlink_to(secret)
    with use_context(_context()):
        assert "outside the pack" not in read_knowledge(topic="link")


def test_read_knowledge_lists_none_when_no_pack_has_topics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _packs(monkeypatch, tmp_path)
    with use_context(_context()):
        reply = read_knowledge(topic="does-not-exist")
    assert "available topics: none" in reply


def test_bundled_shared_react_pack_is_readable_by_any_agent() -> None:
    with use_context(_context("michael")):
        hooks = read_knowledge(topic="react/hooks-and-effects")
        assert hooks.startswith("---")
        index = read_knowledge(topic="react/index")
    assert "react/hooks-and-effects" in index
