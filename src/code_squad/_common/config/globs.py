"""Path globs for routing, ignore lists and project keys.

``**`` matches any number of path segments (including none, as in ``**/x``);
``*`` and ``?`` match within one segment only.
"""

from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
            continue
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        index += 1
    return re.compile("".join(out) + r"\Z")


def glob_match(pattern: str, path: str) -> bool:
    return _compile(pattern).match(path) is not None


def is_glob(pattern: str) -> bool:
    return any(char in pattern for char in "*?[")


def specificity(pattern: str) -> tuple[int, int, int]:
    """Larger tuples are more specific: exact keys beat globs; then fewer wildcards;
    then a longer literal prefix."""
    if not is_glob(pattern):
        return (1, 0, len(pattern))
    wildcards = sum(pattern.count(char) for char in "*?")
    prefix = re.split(r"[*?\[]", pattern, maxsplit=1)[0]
    return (0, -wildcards, len(prefix))
