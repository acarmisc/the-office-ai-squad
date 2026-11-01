"""Helpers behind ``squad config``: schema output, kind detection and validation."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ValidationError

from code_squad._common.config.errors import ConfigError, problems_of
from code_squad._common.config.schema import (
    ProjectEntry,
    ProjectsFile,
    RepoConfig,
    SquadConfig,
    SquadFields,
)
from code_squad._common.config.yaml_io import load_yaml
from code_squad._common.contract import Finding, InvocationRequest

SCHEMA_KINDS: Final[dict[str, type[BaseModel]]] = {
    "config": RepoConfig,
    "projects": ProjectsFile,
    "invocation": InvocationRequest,
    "finding": Finding,
}


def schema_text(kind: str) -> str:
    model = SCHEMA_KINDS[kind]
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


@dataclass
class ValidationReport:
    path: Path
    kind: str
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def detect_kind(path: Path, raw: Any) -> str:
    if isinstance(raw, dict):
        if "projects" in raw or "profiles" in raw:
            return "projects"
        if "match" in raw:
            return "project"
    if path.parent.name == "profiles":
        return "profile"
    if path.name == "squad.yaml":
        return "org"
    return "config"


def _validate_document(kind: str, raw: Any) -> None:
    if kind == "org":
        SquadConfig.model_validate(raw)
    elif kind == "projects":
        ProjectsFile.model_validate(raw)
    elif kind == "project":
        ProjectEntry.model_validate(raw)
    elif kind == "profile":
        SquadFields.model_validate(raw)
    else:
        RepoConfig.model_validate(raw or {})


def validate_file(path: Path, *, kind: str | None = None) -> ValidationReport:
    try:
        raw = load_yaml(path.read_text(encoding="utf-8"), str(path))
    except (OSError, ConfigError) as exc:
        return ValidationReport(path, kind or "unknown", [f"cannot read YAML: {exc}"])
    if raw is not None and not isinstance(raw, dict):
        return ValidationReport(
            path, kind or "unknown", ["top level must be a mapping"]
        )
    chosen = kind or detect_kind(path, raw)
    report = ValidationReport(path, chosen)
    try:
        _validate_document(chosen, raw)
    except ValidationError as exc:
        report.problems = problems_of(exc)
    return report


_SQUAD_SCHEMA_HINTS = ("squad-config.schema.json", "projects.schema.json")


def _is_squad_file(path: Path) -> bool:
    """Directory scans keep only files that look like squad configuration.

    Other YAML (CI workflows, Helm values, manifests) shares directories such as
    ``examples/`` and must not fail validation. Explicit file arguments are always
    validated.
    """
    if path.name == "squad.yaml" or path.name.startswith("projects"):
        return True
    if path.parent.name in ("profiles", ".squad"):
        return True
    try:
        head = path.read_text(encoding="utf-8")[:512]
    except OSError:
        return False
    return any(hint in head for hint in _SQUAD_SCHEMA_HINTS)


def expand_paths(paths: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            candidates = sorted([*path.rglob("*.yaml"), *path.rglob("*.yml")])
            found.extend(c for c in candidates if _is_squad_file(c))
        else:
            found.append(path)
    return found
