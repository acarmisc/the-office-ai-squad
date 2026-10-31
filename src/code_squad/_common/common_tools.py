from __future__ import annotations

import re
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any, Final

from pydantic import ValidationError
from strands import tool
from strands.types.tools import ToolContext

from code_squad._common.context import current
from code_squad._common.contract import FinishPayload

MAX_INVALID_FINISH: Final = 2
_TOPIC: Final = re.compile(r"^[a-z0-9_][a-z0-9_/-]{0,127}$")
_README: Final = "README.md"


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
    """Read a bundled guideline topic for this agent, e.g. 'react/hooks'."""
    agent = current().agent
    if not _TOPIC.match(topic):
        return "invalid topic name"
    knowledge = resources.files(f"code_squad.{agent}").joinpath("knowledge")
    resource = knowledge.joinpath(f"{topic}.md")
    if resource.is_file():
        return resource.read_text(encoding="utf-8")
    available = ", ".join(_topics(knowledge)) or "none"
    return f"topic '{topic}' not found; available topics: {available}"


def _topics(knowledge: Traversable) -> list[str]:
    if not knowledge.is_dir():
        return []
    return sorted(
        entry.name[: -len(".md")]
        for entry in knowledge.iterdir()
        if entry.name.endswith(".md") and entry.name != _README
    )


def _describe(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'arguments'}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False)
    )
