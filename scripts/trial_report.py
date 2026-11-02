"""Print a readable report of one /invocations result for scripts/trial_review.sh.

Usage: trial_report.py RESULT_FILE [--wall-seconds SECONDS]

RESULT_FILE holds the JSON body of a 200 response (use ``-`` for stdin). The wall time
is measured by the caller, because the result carries no timing. Exit 0 when the run
did not fail; exit 1 when ``status`` is ``failed`` or the body is not a result object.
"""

from __future__ import annotations

import json
import sys
from typing import Final

from code_squad._common.ci.report import exit_code as exit_code
from code_squad._common.ci.report import parse_result as parse_result
from code_squad._common.ci.report import render as render
from code_squad._common.ci.report import severity_counts as severity_counts

_USAGE: Final = "usage: trial_report.py RESULT_FILE [--wall-seconds SECONDS]"


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
