from __future__ import annotations

import json
from pathlib import Path

import yaml

from code_squad._common.config.explain import explain, render
from tests.config.support import org_from, run


def test_every_key_has_a_value_and_a_layer(tmp_path: Path) -> None:
    effective = run(
        org=org_from("review:\n  max_findings: 11\n", tmp_path),
        repo="review:\n  chunking: truncate\n",
    )
    rows = {row.key: row for row in explain(effective)}
    assert rows["review.max_findings"].value == 11
    assert rows["review.max_findings"].layer == "org"
    assert rows["review.chunking"].layer == "repo"
    assert rows["review.min_severity_inline"].layer == "default"
    assert all(row.layer for row in rows.values())


def test_json_rendering_carries_provenance_and_rejections(tmp_path: Path) -> None:
    effective = run(
        org=org_from(None, tmp_path),
        repo="vcs:\n  approve_mode: approve\n",
    )
    data = json.loads(render(effective, "json"))
    assert data["config_hash"] == effective.config_hash
    entry = next(
        item for item in data["effective"] if item["key"] == "review.max_findings"
    )
    assert entry == {"key": "review.max_findings", "value": 30, "layer": "default"}
    assert data["rejected_layers"][0]["layer"] == "repo"
    assert any("approve_mode" in v for v in data["rejected_layers"][0]["violations"])
    assert data["warnings"]


def test_yaml_rendering_round_trips(tmp_path: Path) -> None:
    effective = run(org=org_from("review:\n  max_findings: 5\n", tmp_path))
    data = yaml.safe_load(render(effective, "yaml"))
    assert data["config_hash"] == effective.config_hash
    row = next(
        item for item in data["effective"] if item["key"] == "review.max_findings"
    )
    assert row["value"] == 5
    assert row["layer"] == "org"


def test_project_key_is_reported(tmp_path: Path) -> None:
    effective = run(org=org_from(None, tmp_path), project="acme/web-shop")
    assert json.loads(render(effective, "json"))["project_key"] == "acme/web-shop"
