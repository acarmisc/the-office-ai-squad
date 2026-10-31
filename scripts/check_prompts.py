"""Check every agent prompt.md: word budget and required sections."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent / "src" / "code_squad"
_MAX_WORDS = 2500
REQUIRED_SECTIONS: tuple[str, ...] = (
    "## Role and boundaries",
    "## Untrusted content",
    "## Method",
    "## Severity rubric",
    "## Output contract",
    "## Dry-run",
    "## Tools and skills",
    "## Limits",
)


def check_prompt(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    words = len(text.split())
    if words > _MAX_WORDS:
        errors.append(f"{path}: {words} words > {_MAX_WORDS}")
    if not text.lstrip().startswith("# "):
        errors.append(f"{path}: missing title line")
    errors.extend(
        f"{path}: missing section '{section}'"
        for section in REQUIRED_SECTIONS
        if section not in text
    )
    return errors


def main() -> int:
    prompts = sorted(_ROOT.glob("*/prompt.md"))
    errors = [err for p in prompts for err in check_prompt(p)]
    for err in errors:
        print(err)
    print(f"check_prompts: {len(prompts)} prompt(s), {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
