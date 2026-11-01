"""Lightweight local secret scan: fails on token-shaped strings in tracked files."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_PATTERNS: dict[str, re.Pattern[str]] = {
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "gitlab_token": re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
}
_ALLOW_MARKER = "secret-scan: allow"
_SKIP_SUFFIXES = {".png", ".jpg", ".gif", ".ico", ".lock"}


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [Path(p) for p in out.splitlines() if p]


def _scan(path: Path) -> list[str]:
    if path.suffix in _SKIP_SUFFIXES or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    hits: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _ALLOW_MARKER in line:
            continue
        for name, pattern in _PATTERNS.items():
            if pattern.search(line):
                hits.append(f"{path}:{lineno}: {name}")
    return hits


def main() -> int:
    hits = [hit for path in _tracked_files() for hit in _scan(path)]
    for hit in hits:
        print(hit)
    print(f"secret-scan: {len(hits)} finding(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
