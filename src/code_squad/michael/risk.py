"""Deterministic risk tier: diff size, sensitive paths, dependency files and secrets.

Secret-like values are reported by pattern name only; the matched text is never stored.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from code_squad._common.config.globs import glob_match
from code_squad._common.config.schema import RoutingConfig
from code_squad._common.vcs.base import FileDiff

RiskTier = Literal["low", "medium", "high"]

_DEPENDENCY_NAMES: Final = frozenset(
    {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "pom.xml",
        "gradle.lockfile",
        "requirements.txt",
        "pyproject.toml",
        "uv.lock",
        "go.mod",
        "go.sum",
        "Cargo.toml",
        "Cargo.lock",
    }
)
_DEPENDENCY_PREFIXES: Final = ("build.gradle", "requirements")
_SECRET_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("gitlab token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "hard-coded password",
        re.compile(r"(?i)\b(?:password|passwd|pwd)\s*[=:]\s*['\"][^'\"]+['\"]"),
    ),
    (
        "hard-coded api key",
        re.compile(r"(?i)\bapi[_-]?key\s*[=:]\s*['\"][^'\"]{8,}['\"]"),
    ),
)


@dataclass(frozen=True)
class RiskAssessment:
    tier: RiskTier
    reasons: tuple[str, ...]
    changed_lines: int


def risk_tier(diff_files: Sequence[FileDiff], routing: RoutingConfig) -> RiskAssessment:
    high: list[str] = []
    medium: list[str] = []
    lines = sum(_changed_lines(item.patch) for item in diff_files)
    thresholds = routing.size_thresholds
    if lines >= thresholds.high:
        high.append(f"{lines} changed lines (high threshold {thresholds.high})")
    elif lines >= thresholds.medium:
        medium.append(f"{lines} changed lines (medium threshold {thresholds.medium})")
    for item in diff_files:
        if any(glob_match(pattern, item.path) for pattern in routing.sensitive_paths):
            medium.append(f"sensitive path changed: {item.path}")
        if _is_dependency_file(item.path):
            medium.append(f"dependency manifest changed: {item.path}")
        for name in _secret_hits(item.patch):
            high.append(f"secret-like value added ({name}) in {item.path}")
    tier: RiskTier = "high" if high else "medium" if medium else "low"
    return RiskAssessment(tier, tuple(high + medium), lines)


def _changed_lines(patch: str) -> int:
    return sum(1 for _ in _changed(patch))


def _changed(patch: str) -> Iterator[str]:
    for line in patch.split("\n"):
        if line.startswith(("+++ ", "--- ")):
            continue
        if line.startswith(("+", "-")):
            yield line


def _secret_hits(patch: str) -> list[str]:
    names: list[str] = []
    for line in patch.split("\n"):
        if not line.startswith("+") or line.startswith("+++ "):
            continue
        content = line[1:]
        for name, pattern in _SECRET_PATTERNS:
            if pattern.search(content) and name not in names:
                names.append(name)
    return names


def _is_dependency_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name in _DEPENDENCY_NAMES or name.startswith(_DEPENDENCY_PREFIXES)
