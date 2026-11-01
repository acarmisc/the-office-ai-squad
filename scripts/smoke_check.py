"""JSON checks for scripts/smoke_test.sh.

``ping FILE``: the body is ``{"status": "ok"}``.
``invocation FILE AGENT``: the body is a complete, unposted InvocationResult from AGENT.

Exit 0 on success. Failures are printed to stderr with exit 1. A success summary is
printed to stdout for the invocation check.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_USAGE: str = "usage: smoke_check.py ping FILE | invocation FILE AGENT"


def _load(path: str) -> dict[str, Any]:
    data: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("response body is not a JSON object")
    return data


def _ping_problems(data: dict[str, Any]) -> list[str]:
    return [] if data.get("status") == "ok" else ['body is not {"status": "ok"}']


def _invocation_problems(data: dict[str, Any], agent: str) -> list[str]:
    problems: list[str] = []
    if data.get("agent") != agent:
        problems.append(f"agent is {data.get('agent')!r}")
    if data.get("status") != "complete":
        problems.append(f"status is {data.get('status')!r}, expected 'complete'")
    posted = data.get("posted") or {}
    if int(posted.get("notes", 0)) or int(posted.get("discussions", 0)):
        problems.append(f"external write recorded: {posted!r}")
    if posted.get("status") or posted.get("urls"):
        problems.append(f"status or URLs were posted: {posted!r}")
    return problems


def _invocation_summary(data: dict[str, Any]) -> str:
    stats = data.get("stats") or {}
    posted = data.get("posted") or {}
    tool_calls = json.dumps(stats.get("tool_calls") or {}, sort_keys=True)
    findings = len(data.get("findings") or [])
    return (
        f"status={data.get('status')} verdict={data.get('verdict')} "
        f"findings={findings} tool_calls={tool_calls} "
        f"posted_notes={posted.get('notes', 0)} "
        f"posted_discussions={posted.get('discussions', 0)}"
    )


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "ping" and len(argv) == 2:
        problems = _ping_problems(_load(argv[1]))
        return _report(problems, "ping ok")
    if len(argv) == 3 and argv[0] == "invocation":
        data = _load(argv[1])
        problems = _invocation_problems(data, argv[2])
        if problems:
            return _report(problems, "")
        print(_invocation_summary(data))
        return 0
    print(_USAGE, file=sys.stderr)
    return 2


def _report(problems: list[str], success: str) -> int:
    if problems:
        print("; ".join(problems), file=sys.stderr)
        return 1
    if success:
        print(success)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
