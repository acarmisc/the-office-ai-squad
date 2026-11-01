"""Repository baseline of accepted findings. Expired entries are ignored."""

from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from code_squad._common.config.errors import ConfigError, problems_of
from code_squad._common.config.schema import Baseline, BaselineEntry
from code_squad._common.config.yaml_io import load_yaml


def load_baseline(text: str) -> Baseline:
    loaded = load_yaml(text, "baseline")
    try:
        return Baseline.model_validate(loaded or {})
    except ValidationError as exc:
        raise ConfigError("baseline is invalid", problems_of(exc)) from exc


def active_entries(
    baseline: Baseline, today: date
) -> tuple[list[BaselineEntry], list[str]]:
    """Return entries still in force, and a warning for each expired one."""
    active: list[BaselineEntry] = []
    warnings: list[str] = []
    for entry in baseline.accepted:
        if entry.expires < today:
            label = entry.finding_id or entry.rule_id or "?"
            warnings.append(
                f"baseline entry {label} in {entry.file} expired {entry.expires}"
            )
        else:
            active.append(entry)
    return active, warnings
