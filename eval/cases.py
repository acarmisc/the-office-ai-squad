"""Golden case model: seeded defects, must-not-flag lines and the replay script."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from code_squad._common.contract import Severity

_SHA: Final = r"^[0-9a-f]{40}$"
Sha = Annotated[str, StringConstraints(pattern=_SHA)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExpectedFinding(_Strict):
    id: str = Field(min_length=1, max_length=64)
    file: str = Field(min_length=1)
    lines: tuple[int, int]
    category: str = Field(min_length=1)
    severity: Severity


class MustNotFlag(_Strict):
    file: str = Field(min_length=1)
    lines: tuple[int, int]
    reason: str = Field(min_length=1)


class GoldenCase(_Strict):
    id: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1)
    agent: Literal["jim", "angela"]
    fixture: str = Field(min_length=1)
    project: str = Field(min_length=3)
    target: str = Field(pattern=r"^\d+$")
    title: str = Field(min_length=1, max_length=200)
    head_sha: Sha
    base_sha: Sha
    added_files: tuple[str, ...] = Field(min_length=1)
    expected: tuple[ExpectedFinding, ...] = ()
    must_not_flag: tuple[MustNotFlag, ...] = ()
    injection: str | None = None
    replay: str = Field(min_length=1)


def load_case(path: Path) -> GoldenCase:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: a case must be a mapping")
    return GoldenCase.model_validate(raw)


def load_cases(directory: Path, only: tuple[str, ...] = ()) -> list[GoldenCase]:
    cases = [load_case(path) for path in sorted(directory.glob("*.yaml"))]
    if only:
        cases = [case for case in cases if case.id in only]
    return cases
