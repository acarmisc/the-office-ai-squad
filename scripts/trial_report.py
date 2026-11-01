"""Print a readable report of one /invocations result for scripts/trial_review.sh.

Usage: trial_report.py RESULT_FILE [--wall-seconds SECONDS]

RESULT_FILE holds the JSON body of a 200 response (use ``-`` for stdin). The wall time
is measured by the caller, because the result carries no timing. Exit 0 when the run
did not fail; exit 1 when ``status`` is ``failed`` or the body is not a result object.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Final

_USAGE: Final = "usage: trial_report.py RESULT_FILE [--wall-seconds SECONDS]"
_SEVERITIES: Final = ("blocker", "major", "minor", "nit")
_FAILED: Final = "failed"


def parse_result(text: str) -> dict[str, Any]:
    data: Any = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("result is not a JSON object")
    return data


def severity_counts(findings: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter(
        str(item.get("severity", "unknown")) for item in findings
    )
    ordered = {name: counter.get(name, 0) for name in _SEVERITIES}
    for name, count in sorted(counter.items()):
        if name not in ordered:
            ordered[name] = count
    return ordered


def exit_code(data: Mapping[str, Any]) -> int:
    return 1 if data.get("status") == _FAILED else 0


def render(data: Mapping[str, Any], wall_seconds: float | None) -> str:
    findings = _list(data.get("findings"))
    stats = _mapping(data.get("stats"))
    posted = _mapping(data.get("posted"))
    counts = severity_counts(findings)
    lines = [
        f"agent:    {data.get('agent')}",
        f"status:   {data.get('status')}",
        f"verdict:  {data.get('verdict')}",
        "findings: "
        f"{len(findings)} ("
        + ", ".join(f"{name} {count}" for name, count in counts.items())
        + ")",
        f"posted:   notes={posted.get('notes', 0)} "
        f"discussions={posted.get('discussions', 0)} status={posted.get('status')}",
        f"tokens:   input={stats.get('input_tokens', 0)} "
        f"output={stats.get('output_tokens', 0)}",
        f"turns:    {stats.get('iterations', 0)}",
        f"tools:    {json.dumps(stats.get('tool_calls') or {}, sort_keys=True)}",
    ]
    if wall_seconds is not None:
        lines.append(f"wall:     {wall_seconds:.1f} s")
    lines.extend(_finding_lines(findings))
    warnings = data.get("warnings")
    lines.append("warnings:")
    if isinstance(warnings, list) and warnings:
        lines.extend(f"  - {item}" for item in warnings)
    else:
        lines.append("  none")
    return "\n".join(lines)


_MAX_LISTED = 20


def _finding_lines(findings: Sequence[Mapping[str, Any]]) -> list[str]:
    if not findings:
        return []
    lines = ["top findings:"]
    for item in findings[:_MAX_LISTED]:
        where = f"{item.get('file')}:{item.get('line_start')}"
        lines.append(
            f"  - [{item.get('severity')}/{item.get('confidence')}] "
            f"{item.get('agent')} {item.get('rule_id')} {where} {item.get('title')}"
        )
    if len(findings) > _MAX_LISTED:
        lines.append(f"  ... {len(findings) - _MAX_LISTED} more in the JSON result")
    return lines


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def main(argv: list[str]) -> int:
    wall: float | None = None
    args = list(argv)
    if "--wall-seconds" in args:
        index = args.index("--wall-seconds")
        if index + 1 >= len(args):
            print(_USAGE, file=sys.stderr)
            return 2
        wall = float(args[index + 1])
        del args[index : index + 2]
    if len(args) != 1:
        print(_USAGE, file=sys.stderr)
        return 2
    text = sys.stdin.read() if args[0] == "-" else _read(args[0])
    try:
        data = parse_result(text)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(render(data, wall))
    return exit_code(data)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
