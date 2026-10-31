from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from typing import Final

from code_squad._common.skills.model import Skill, SkillLimits

REMOVED_MARKER: Final = "[removed: instruction overriding system rules]"
TRUNCATED_MARKER: Final = "\n[truncated: skill body exceeds the size limit]"
MIN_USEFUL_BYTES: Final = 512

_OVERRIDE_TARGET: Final = (
    r"(?:(?:all|any|the|your)\s+)?(?:(?:previous|prior|above|earlier|system)\s+)?"
    r"(?:instructions|rules|guidelines)\b"
)
_HIJACK_PATTERNS: Final = (
    rf"\bignore\s+{_OVERRIDE_TARGET}",
    rf"\bdisregard\s+{_OVERRIDE_TARGET}",
    r"\bdisable\s+dry[- ]?run\b",
    r"\bset\s+post\s+(?:to\s+)?true\b",
    r"\bpost\s*[:=]\s*true\b",
    r"\byou\s+(?:may|can|are\s+allowed\s+to)\s+(?:call|use)\s+"
    r"(?:(?:any|new|additional)\s+){0,2}tools?\b",
    r"\bapprove\s+(?:this|the)\s+(?:merge|change|pull)\s+request\b",
    r"\bdo\s+not\s+report\b",
    r"\bchange\s+the\s+output\s+(?:format|schema)\b",
)
_HIJACK: Final = tuple(re.compile(p, re.IGNORECASE) for p in _HIJACK_PATTERNS)
# Zero-width space, zero-width non-joiner and joiner, word joiner, byte order mark.
_INVISIBLE: Final = re.compile("[​-‍⁠﻿]")


def is_hijack_line(line: str) -> bool:
    normalized = _INVISIBLE.sub("", unicodedata.normalize("NFKC", line))
    return any(pattern.search(normalized) for pattern in _HIJACK)


def sanitize_text(text: str, *, skill: str, field: str) -> tuple[str, list[str]]:
    lines = text.split("\n")
    flags = [is_hijack_line(line) for line in lines]
    if not any(flags):
        return text, []
    kept = [
        REMOVED_MARKER if flag else line
        for line, flag in zip(lines, flags, strict=True)
    ]
    count = sum(flags)
    warning = (
        f"skill {skill}: removed {count} line(s) from {field} "
        "that tried to override system rules"
    )
    return "\n".join(kept), [warning]


def enforce_limits(
    skills: list[Skill], limits: SkillLimits, warnings: list[str]
) -> list[Skill]:
    counted = _apply_count(skills, limits.max_skills, warnings)
    sized = [_cap_skill(skill, limits.max_skill_bytes, warnings) for skill in counted]
    return _apply_total(sized, limits.max_total_bytes, warnings)


def _apply_count(skills: list[Skill], limit: int, warnings: list[str]) -> list[Skill]:
    for skill in skills[limit:]:
        warnings.append(
            f"skill {skill.name} dropped: more than {limit} skills selected"
        )
    return skills[:limit]


def _cap_skill(skill: Skill, limit: int, warnings: list[str]) -> Skill:
    if _size(skill.body) <= limit:
        return skill
    warnings.append(f"skill {skill.name} truncated to {limit} bytes")
    return replace(skill, body=_truncate(skill.body, limit), truncated=True)


def _apply_total(skills: list[Skill], limit: int, warnings: list[str]) -> list[Skill]:
    kept: list[Skill] = []
    remaining = limit
    for skill in skills:
        size = _size(skill.body)
        if size <= remaining:
            kept.append(skill)
            remaining -= size
        elif remaining < MIN_USEFUL_BYTES:
            warnings.append(
                f"skill {skill.name} dropped: total skill size exceeds {limit} bytes"
            )
        else:
            warnings.append(
                f"skill {skill.name} truncated to fit the total limit of {limit} bytes"
            )
            kept.append(
                replace(skill, body=_truncate(skill.body, remaining), truncated=True)
            )
            remaining = 0
    return kept


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def _truncate(text: str, limit: int) -> str:
    marker_size = _size(TRUNCATED_MARKER)
    budget = max(limit - marker_size, 0)
    head = text.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return head + TRUNCATED_MARKER
