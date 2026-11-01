from __future__ import annotations

import json
import re
import shlex
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from code_squad._common.config.globs import glob_match
from code_squad._common.sandbox.errors import SandboxError
from code_squad._common.sandbox.policy import validate_ref

PackageManager = Literal["npm", "pnpm", "yarn"]
TaskScope = Literal["default", "requires_protected_paths"]

MAX_TITLE_CHARS: Final = 200
MAX_BODY_CHARS: Final = 60_000
MAX_SUMMARY_CHARS: Final = 200
_SCRIPT_ORDER: Final = ("lint", "typecheck", "test", "build")
_TASK_KEY: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_NON_ALNUM: Final = re.compile(r"[^a-z0-9]+")
_PLACEHOLDER: Final = re.compile(r"\{(\w+)\}")
_FALLBACK_SLUG: Final = "change"


class WorkflowError(ValueError):
    pass


@dataclass(frozen=True)
class CheckOutcome:
    name: str
    passed: bool
    exit_code: int

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "exit_code": self.exit_code}


def check_task_key(task_key: str) -> str:
    if not _TASK_KEY.match(task_key):
        raise WorkflowError(
            "task key must start with a letter or digit and contain only letters, "
            "digits, '-' or '_' (at most 64 characters)"
        )
    return task_key


def slugify(text: str, max_len: int = 40) -> str:
    if max_len < 1:
        raise WorkflowError("max_len must be at least 1")
    slug = _NON_ALNUM.sub("-", text.lower()).strip("-")
    if len(slug) > max_len:
        cut = slug[:max_len]
        if cut.rfind("-") > 0:
            cut = cut[: cut.rfind("-")]
        slug = cut.strip("-")
    return slug or _FALLBACK_SLUG


def branch_name(template: str, task_key: str, summary: str) -> str:
    name = template.replace("{task_key}", check_task_key(task_key))
    name = name.replace("{slug}", slugify(summary))
    try:
        return validate_ref(name)
    except SandboxError as exc:
        raise WorkflowError(f"branch name is not valid: {name!r}") from exc


def detect_package_manager(names: Iterable[str]) -> PackageManager:
    found = set(names)
    if "pnpm-lock.yaml" in found:
        return "pnpm"
    if "yarn.lock" in found:
        return "yarn"
    return "npm"


def install_command(package_manager: PackageManager, *, locked: bool) -> list[str]:
    if package_manager == "npm":
        return ["npm", "ci"] if locked else ["npm", "install"]
    return [package_manager, "install", "--frozen-lockfile"]


def declares_recipe(text: str, name: str, *, make: bool) -> bool:
    if make:
        pattern = rf"^{re.escape(name)}\s*:(?!=)"
    else:
        pattern = rf"^{re.escape(name)}(\s[^:=\n]*)?:(?!=)"
    return re.search(pattern, text, re.MULTILINE) is not None


def detect_checks(
    package_json_text: str | None,
    has_justfile: bool,
    has_makefile: bool,
    override: list[str] | None,
    *,
    package_manager: PackageManager = "npm",
) -> list[list[str]]:
    """Commands that verify the change, as argv lists.

    ``has_justfile`` and ``has_makefile`` mean the file declares a ``check`` recipe.
    """
    if override is not None:
        return [_parse_command(item) for item in override]
    if has_justfile:
        return [["just", "check"]]
    if has_makefile:
        return [["make", "check"]]
    return _script_checks(package_json_text, package_manager)


def _parse_command(text: str) -> list[str]:
    try:
        parts = shlex.split(text)
    except ValueError as exc:
        raise WorkflowError(f"check command cannot be parsed: {text!r}") from exc
    if not parts:
        raise WorkflowError("check command is empty")
    return parts


def _script_checks(
    text: str | None, package_manager: PackageManager
) -> list[list[str]]:
    if text is None:
        return []
    data = _load_object(text)
    scripts = _mapping(data.get("scripts"))
    dependencies = {
        **_mapping(data.get("dependencies")),
        **_mapping(data.get("devDependencies")),
    }
    commands: list[list[str]] = []
    for name in _SCRIPT_ORDER:
        if isinstance(scripts.get(name), str):
            commands.append([package_manager, "run", name])
        elif name == "typecheck" and "typescript" in dependencies:
            commands.append(["npx", "--no", "tsc", "--noEmit"])
    return commands


def _load_object(text: str) -> dict[str, Any]:
    try:
        data: Any = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def protected_path_violations(
    changed: Sequence[str], protected_globs: Sequence[str], scope: TaskScope
) -> list[str]:
    """Protected paths that must not be committed. Empty when the task requires them."""
    if scope == "requires_protected_paths":
        return []
    return protected_paths_touched(changed, protected_globs)


def protected_paths_touched(
    changed: Sequence[str], protected_globs: Sequence[str]
) -> list[str]:
    return sorted(
        {
            path
            for path in changed
            if any(glob_match(pattern, path) for pattern in protected_globs)
        }
    )


def commit_message(template: str, *, summary: str, task_key: str) -> str:
    _check_summary(summary)
    text = _fill(template, {"summary": summary, "task_key": task_key})
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    if not first_line:
        raise WorkflowError("commit message is empty")
    return first_line[:MAX_SUMMARY_CHARS]


def render_title(template: str, *, summary: str, task_key: str) -> str:
    _check_summary(summary)
    text = _fill(template, {"summary": summary, "task_key": task_key})
    return " ".join(text.split())[:MAX_TITLE_CHARS]


def render_mr_body(
    template: str,
    *,
    what: str,
    why: str,
    how_tested: str,
    risks: str,
    checks: Sequence[CheckOutcome],
    protected_touched: Sequence[str],
) -> str:
    values = {
        "summary": what,
        "what": what,
        "why": why,
        "tests": how_tested,
        "how_tested": how_tested,
        "risks": risks,
        "checks": checks_table(checks),
    }
    body = _fill(template, values)
    if "{checks}" not in template:
        body = f"{body.rstrip()}\n\n## Checks\n\n{checks_table(checks)}"
    if protected_touched:
        body = f"{body.rstrip()}\n\n{_protected_section(protected_touched)}"
    footer = "_Opened by pam (AI-generated). A human reviews and merges this change._"
    return f"{body.rstrip()}\n\n{footer}\n"[:MAX_BODY_CHARS]


def checks_table(checks: Sequence[CheckOutcome]) -> str:
    if not checks:
        return "Not run: no checks were detected or configured for this repository."
    rows = [
        f"| {_cell(item.name)} | {'pass' if item.passed else 'FAIL'} | "
        f"{item.exit_code} |"
        for item in checks
    ]
    return "\n".join(["| Check | Result | Exit code |", "|---|---|---|", *rows])


def _protected_section(paths: Sequence[str]) -> str:
    bullets = "\n".join(f"- `{path}`" for path in paths)
    return (
        "## Protected paths touched\n\n"
        f"{bullets}\n\nThese paths were changed because the task requires them."
    )


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _check_summary(summary: str) -> None:
    if not summary.strip() or any(ch in summary for ch in "\r\n\x00"):
        raise WorkflowError("summary must be a single non-empty line")


def _fill(template: str, values: Mapping[str, str]) -> str:
    return _PLACEHOLDER.sub(
        lambda match: values.get(match.group(1), match.group(0)), template
    )
