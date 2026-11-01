"""Bump the chart version, appVersion and image tag in place.

``--version`` sets ``version`` and ``appVersion`` in Chart.yaml. ``--tag`` sets
``image.tag`` in values.yaml. Edits are line based, so the comments and layout of both
files survive. ``--dry-run`` prints a unified diff and writes nothing.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
CHART_DIR: Final[Path] = ROOT / "deploy" / "helm" / "code-squad"
_TAG_PATTERN: Final = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
_VERSION_PATTERN: Final = re.compile(
    r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_TOP_LEVEL_KEY: Final = re.compile(r"^[A-Za-z_][\w-]*:")


class BumpError(ValueError):
    """Invalid arguments or a file that does not have the expected keys."""


@dataclass(frozen=True)
class Change:
    path: Path
    before: str
    after: str

    @property
    def changed(self) -> bool:
        return self.before != self.after


def validate_tag(tag: str) -> str:
    if not _TAG_PATTERN.match(tag):
        raise BumpError(f"invalid image tag {tag!r}")
    return tag


def validate_version(version: str) -> str:
    if not _VERSION_PATTERN.match(version):
        raise BumpError(f"version must be semantic (X.Y.Z), got {version!r}")
    return version


def _replace_top_level(text: str, key: str, value: str, path: Path) -> str:
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    if not pattern.search(text):
        raise BumpError(f"{path.name}: top-level key {key!r} not found")
    return pattern.sub(lambda _match: f'{key}: "{value}"', text, count=1)


def _replace_image_tag(text: str, tag: str, path: Path) -> str:
    lines = text.split("\n")
    try:
        start = lines.index("image:")
    except ValueError as exc:
        raise BumpError(f"{path.name}: top-level 'image:' block not found") from exc
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith(" ") and _TOP_LEVEL_KEY.match(line):
            break
        if re.match(r"^\s+tag:", line):
            indent = line[: len(line) - len(line.lstrip())]
            lines[index] = f'{indent}tag: "{tag}"'
            return "\n".join(lines)
    raise BumpError(f"{path.name}: image.tag not found in the image block")


def plan(chart_dir: Path, tag: str | None, version: str | None) -> list[Change]:
    if tag is None and version is None:
        raise BumpError("pass --tag, --version or both")
    changes: list[Change] = []
    if version is not None:
        validate_version(version)
        chart = chart_dir / "Chart.yaml"
        before = chart.read_text(encoding="utf-8")
        after = _replace_top_level(before, "version", version, chart)
        after = _replace_top_level(after, "appVersion", version, chart)
        changes.append(Change(chart, before, after))
    if tag is not None:
        validate_tag(tag)
        values = chart_dir / "values.yaml"
        before = values.read_text(encoding="utf-8")
        changes.append(Change(values, before, _replace_image_tag(before, tag, values)))
    return changes


def render_diff(change: Change) -> str:
    rel = change.path.name
    diff = difflib.unified_diff(
        change.before.splitlines(keepends=True),
        change.after.splitlines(keepends=True),
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
    )
    return "".join(diff)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="image tag for values.yaml image.tag")
    parser.add_argument("--version", help="semantic version for Chart.yaml")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the diff, write nothing"
    )
    parser.add_argument(
        "--chart-dir", type=Path, default=CHART_DIR, help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)
    try:
        changes = plan(args.chart_dir, args.tag, args.version)
    except (BumpError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    pending = [change for change in changes if change.changed]
    if not pending:
        print("nothing to change")
        return 0
    for change in pending:
        sys.stdout.write(render_diff(change))
    if args.dry_run:
        print("dry run: no files written")
        return 0
    for change in pending:
        change.path.write_text(change.after, encoding="utf-8")
        print(f"updated {change.path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
