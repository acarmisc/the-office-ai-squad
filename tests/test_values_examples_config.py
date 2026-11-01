from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from code_squad._common.config.schema import ProjectsFile, SquadConfig

_CHART = Path(__file__).resolve().parent.parent / "deploy" / "helm" / "code-squad"
_VALUES = sorted([_CHART / "values.yaml", *(_CHART / "values-examples").glob("*.yaml")])


def _config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config = data.get("config") or {}
    assert isinstance(config, dict)
    return config


@pytest.mark.parametrize("path", _VALUES, ids=lambda p: p.name)
def test_embedded_org_config_matches_the_schema(path: Path) -> None:
    SquadConfig.model_validate(_config(path).get("org") or {})


@pytest.mark.parametrize("path", _VALUES, ids=lambda p: p.name)
def test_embedded_projects_match_the_schema(path: Path) -> None:
    ProjectsFile.model_validate(_config(path).get("projects") or {})
