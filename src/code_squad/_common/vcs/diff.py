from __future__ import annotations

import re
from typing import Final

from code_squad._common.vcs.base import FileDiff, Hunk

_HUNK_HEADER: Final = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_patch(patch: str) -> tuple[Hunk, ...]:
    hunks: list[Hunk] = []
    header: re.Match[str] | None = None
    added: set[int] = set()
    new_line = 0
    for raw in patch.split("\n"):
        match = _HUNK_HEADER.match(raw)
        if match is not None:
            if header is not None:
                hunks.append(_build(header, added))
            header = match
            added = set()
            new_line = int(match.group(3))
            continue
        if header is None or raw.startswith("\\"):
            continue
        new_line = _consume(raw, new_line, added)
    if header is not None:
        hunks.append(_build(header, added))
    return tuple(hunks)


def _consume(raw: str, new_line: int, added: set[int]) -> int:
    if raw.startswith("+"):
        added.add(new_line)
        return new_line + 1
    if raw.startswith("-"):
        return new_line
    return new_line + 1


def _build(match: re.Match[str], added: set[int]) -> Hunk:
    return Hunk(
        old_start=int(match.group(1)),
        old_lines=_count(match.group(2)),
        new_start=int(match.group(3)),
        new_lines=_count(match.group(4)),
        added_lines=frozenset(added),
    )


def _count(value: str | None) -> int:
    return 1 if value is None else int(value)


_MAX_RANGE_LINES: Final = 1000


def added_range(file_diff: FileDiff, start: int, end: int) -> bool:
    """True when every line of ``start..end`` is an added line of the new file."""
    lo, hi = min(start, end), max(start, end)
    if hi - lo >= _MAX_RANGE_LINES:
        return False
    added: set[int] = set()
    for hunk in file_diff.hunks:
        added |= hunk.added_lines
    return all(line in added for line in range(lo, hi + 1))


def line_in_changed_hunk(file_diff: FileDiff, start: int, end: int) -> bool:
    lo, hi = min(start, end), max(start, end)
    return any(
        hunk.new_lines > 0 and hunk.new_start <= hi and lo <= hunk.new_end
        for hunk in file_diff.hunks
    )
