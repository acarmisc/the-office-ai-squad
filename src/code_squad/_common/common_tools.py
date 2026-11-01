from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from importlib import resources
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError
from strands import tool
from strands.types.tools import ToolContext

from code_squad._common.context import current
from code_squad._common.contract import FinishPayload

MAX_INVALID_FINISH: Final = 2
SHARED_KNOWLEDGE_PACKAGE: Final = "code_squad._common"
_TOPIC: Final = re.compile(r"^[a-z0-9_][a-z0-9_/-]{0,127}$")
_TOPIC_SEGMENT: Final = re.compile(r"^[a-z0-9_][a-z0-9_-]*$")
_README: Final = "README.md"
_EXTRA_DIRS_KEY: Final = "knowledge_extra_dirs"


@tool(context=True)
def finish(
    verdict: str,
    summary: str,
    findings: list[dict[str, Any]],
    tool_context: ToolContext,
    data: dict[str, Any] | None = None,
) -> str:
    """Record the final result and end the run. Call exactly once when work is done.

    Args:
        verdict: One of approve, comment, request_changes.
        summary: Short professional summary for the caller (at most 4000 characters).
        findings: Zero or more findings. Each needs agent, rule_id, category,
            severity (blocker, major, minor, nit), confidence (high, medium, low),
            file, line_start, line_end, head_sha, title (at most 200 characters) and
            rationale. Optional: suggestion, references, failure_scenario (required
            for blockers).
        data: Optional agent-specific structured output.
    """
    ctx = current()
    try:
        payload = FinishPayload.model_validate(
            {
                "verdict": verdict,
                "summary": summary,
                "findings": findings,
                "data": data or {},
            }
        )
    except ValidationError as exc:
        ctx.invalid_finish_attempts += 1
        if ctx.invalid_finish_attempts >= MAX_INVALID_FINISH:
            tool_context.agent.cancel(after_current_tools=True)
            return "finish rejected twice; the run stops without a result"
        return (
            f"finish rejected: {_describe(exc)}. "
            "Correct the arguments and call finish again."
        )
    ctx.finish_result = payload
    tool_context.agent.cancel(after_current_tools=True)
    return "finish accepted"


@tool
def read_knowledge(topic: str) -> str:
    """Read a bundled guideline topic, e.g. 'react/hooks-and-effects' or 'java/index'.

    Topics come from the agent's own pack first, then the shared pack, then extra
    directories from configuration. Use an index topic to see what a pack covers.

    Args:
        topic: Topic id: the knowledge file path without the .md extension.
    """
    ctx = current()
    if not _valid_topic(topic):
        return "invalid topic name"
    roots = _knowledge_roots(ctx.agent, _extra_dirs(ctx.services))
    for root in roots:
        text = _read_topic(root, topic)
        if text is not None:
            return text
    available = ", ".join(_all_topics(roots)) or "none"
    return f"topic '{topic}' not found; available topics: {available}"


def _valid_topic(topic: str) -> bool:
    if not _TOPIC.match(topic):
        return False
    return all(_TOPIC_SEGMENT.match(part) for part in topic.split("/"))


def _knowledge_roots(agent: str, extra: Sequence[Path]) -> list[Path]:
    roots = [_package_knowledge(f"code_squad.{agent}")]
    roots.append(_package_knowledge(SHARED_KNOWLEDGE_PACKAGE))
    roots.extend(extra)
    return [root for root in roots if root is not None]


def _package_knowledge(package: str) -> Path | None:
    try:
        base = resources.files(package).joinpath("knowledge")
    except (ModuleNotFoundError, TypeError):
        return None
    return Path(str(base))


def _extra_dirs(services: dict[str, Any]) -> list[Path]:
    value = services.get(_EXTRA_DIRS_KEY)
    if not isinstance(value, list):
        return []
    dirs: list[Path] = []
    for item in value:
        if isinstance(item, str) and Path(item).is_absolute():
            dirs.append(Path(item))
    return dirs


def _read_topic(root: Path, topic: str) -> str | None:
    if not root.is_dir():
        return None
    base = root.resolve()
    target = (base / f"{topic}.md").resolve()
    if not target.is_relative_to(base) or not target.is_file():
        return None
    return target.read_text(encoding="utf-8")


def _all_topics(roots: Iterable[Path]) -> list[str]:
    found: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            if path.name == _README or not path.is_file():
                continue
            topic = path.relative_to(root).with_suffix("").as_posix()
            if _valid_topic(topic):
                found.add(topic)
    return sorted(found)


def _describe(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'arguments'}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False)
    )
