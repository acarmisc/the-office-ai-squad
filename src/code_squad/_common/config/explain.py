"""Effective configuration with provenance: which layer set each key."""

from __future__ import annotations

import json
from typing import Any, Literal, NamedTuple

import yaml

from code_squad._common.config.loader import EffectiveConfig


class ExplainRow(NamedTuple):
    key: str
    value: Any
    layer: str


def explain(effective: EffectiveConfig) -> list[ExplainRow]:
    rows: list[ExplainRow] = []
    _flatten(effective.config.model_dump(mode="json"), "", effective.provenance, rows)
    return rows


def _flatten(
    node: dict[str, Any],
    prefix: str,
    provenance: dict[str, str],
    rows: list[ExplainRow],
) -> None:
    for key, value in node.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            _flatten(value, f"{path}.", provenance, rows)
        else:
            rows.append(ExplainRow(path, value, provenance.get(path, "default")))


def document(effective: EffectiveConfig) -> dict[str, Any]:
    return {
        "config_hash": effective.config_hash,
        "project_key": effective.project_key,
        "effective": [
            {"key": row.key, "value": row.value, "layer": row.layer}
            for row in explain(effective)
        ],
        "warnings": list(effective.warnings),
        "rejected_layers": [
            {
                "layer": layer.layer,
                "violations": [str(item) for item in layer.violations],
            }
            for layer in effective.rejected_layers
        ],
    }


def render(effective: EffectiveConfig, fmt: Literal["yaml", "json"]) -> str:
    data = document(effective)
    if fmt == "json":
        return json.dumps(data, indent=2, default=str) + "\n"
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
