"""Bump the chart version, appVersion and image tag in place.

``--version`` sets ``version`` and ``appVersion`` in Chart.yaml, the sandbox image tag
in values.yaml, ``project.version`` in pyproject.toml, ``__version__`` in the package
and the default ``image`` of the composite action in action.yml, so a release tag
``vX.Y.Z`` matches every place the release workflow checks.
``--tag`` sets ``image.tag`` in values.yaml (leave it unset to follow appVersion).
Edits are line based, so comments and layout survive. ``--dry-run`` prints a
unified diff and writes nothing.
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
_SANDBOX_IMAGE: Final = re.compile(
    r"^(?P<prefix>\s+image:\s*\S*code-squad-sandbox-node:)(?P<tag>\S+)\s*$",
    re.MULTILINE,
)
_PYPROJECT_VERSION: Final = re.compile(r'^version = "[^"]*"$', re.MULTILINE)
_PACKAGE_VERSION: Final = re.compile(r'^__version__ = "[^"]*"$', re.MULTILINE)
_CATALOG_VERSION: Final = re.compile(
    r"^(\s+ai-agent\.io/version: )'[^']*'$", re.MULTILINE
)
_ACTION_IMAGE: Final = re.compile(
    r'^(\s+default: "ghcr\.io/[^"\s:]+):[^"\s]+"\s*$', re.MULTILINE
)


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


def _sub_once(pattern: re.Pattern[str], text: str, repl: str, path: Path) -> str:
    if not pattern.search(text):
        raise BumpError(f"{path.name}: expected version line not found")
    return pattern.sub(lambda _m: repl, text, count=1)


def _replace_sandbox_tag(text: str, version: str, path: Path) -> str:
    if not _SANDBOX_IMAGE.search(text):
        raise BumpError(f"{path.name}: sandbox image line not found")
    return _SANDBOX_IMAGE.sub(
        lambda match: f"{match.group('prefix')}{version}", text, count=1
    )


def _replace_action_image(text: str, version: str, path: Path) -> str:
    if not _ACTION_IMAGE.search(text):
        raise BumpError(f"{path.name}: image input default not found")
    return _ACTION_IMAGE.sub(
        lambda match: f'{match.group(1)}:{version}"', text, count=1
    )


def _version_changes(chart_dir: Path, root: Path, version: str) -> list[Change]:
    chart = chart_dir / "Chart.yaml"
    before = chart.read_text(encoding="utf-8")
    after = _replace_top_level(before, "version", version, chart)
    after = _replace_top_level(after, "appVersion", version, chart)
    changes = [Change(chart, before, after)]
    values = chart_dir / "values.yaml"
    before = values.read_text(encoding="utf-8")
    changes.append(
        Change(values, before, _replace_sandbox_tag(before, version, values))
    )
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        before = pyproject.read_text(encoding="utf-8")
        repl = f'version = "{version}"'
        changes.append(
            Change(
                pyproject,
                before,
                _sub_once(_PYPROJECT_VERSION, before, repl, pyproject),
            )
        )
    package = root / "src" / "code_squad" / "__init__.py"
    if package.is_file():
        before = package.read_text(encoding="utf-8")
        repl = f'__version__ = "{version}"'
        changes.append(
            Change(package, before, _sub_once(_PACKAGE_VERSION, before, repl, package))
        )
    catalog = root / "catalog-info.yaml"
    if catalog.is_file():
        before = catalog.read_text(encoding="utf-8")
        after = _CATALOG_VERSION.sub(lambda m: f"{m.group(1)}'{version}'", before)
        changes.append(Change(catalog, before, after))
    action = root / "action.yml"
    if action.is_file():
        before = action.read_text(encoding="utf-8")
        changes.append(
            Change(action, before, _replace_action_image(before, version, action))
        )
    return changes


def plan(
    chart_dir: Path,
    tag: str | None,
    version: str | None,
    root: Path | None = None,
) -> list[Change]:
    if tag is None and version is None:
        raise BumpError("pass --tag, --version or both")
    changes: list[Change] = []
    if version is not None:
        validate_version(version)
        base = root if root is not None else chart_dir
        changes.extend(_version_changes(chart_dir, base, version))
    if tag is not None:
        validate_tag(tag)
        values = chart_dir / "values.yaml"
        current = next((c for c in changes if c.path == values), None)
        before = current.after if current else values.read_text(encoding="utf-8")
        after = _replace_image_tag(before, tag, values)
        if current:
            changes[changes.index(current)] = Change(values, current.before, after)
        else:
            changes.append(Change(values, before, after))
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
        root = ROOT if args.chart_dir == CHART_DIR else None
        changes = plan(args.chart_dir, args.tag, args.version, root)
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
