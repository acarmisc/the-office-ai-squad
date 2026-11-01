from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

from code_squad._common.config.commands import validate_file
from code_squad._common.config.loader import (
    ConfigSources,
    load_org,
    load_registry,
    resolve,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
ORG = EXAMPLES / "org"
ORG_FILE = ORG / "squad.yaml"
PROJECTS = ORG / "projects.yaml"
PROFILES = ORG / "profiles"


def _example_files() -> list[Path]:
    org = sorted(ORG.rglob("*.yaml"))
    repo = sorted((EXAMPLES / "repo").glob("**/.squad/*.y*ml"))
    return [*org, *repo]


def _as_json(raw: Any) -> Any:
    """YAML dates are date objects; JSON Schema sees them as ISO strings."""
    return json.loads(json.dumps(raw, default=str))


def _schema(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (ROOT / "schemas" / name).read_text(encoding="utf-8")
    )
    return loaded


@pytest.mark.parametrize(
    "path", _example_files(), ids=lambda p: str(p.relative_to(ROOT))
)
def test_every_example_validates(path: Path) -> None:
    report = validate_file(path)
    assert report.ok, report.problems


@pytest.mark.parametrize(
    "path", _example_files(), ids=lambda p: str(p.relative_to(ROOT))
)
def test_every_example_starts_with_the_schema_hint(path: Path) -> None:
    first = path.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("# yaml-language-server: $schema="), path
    target = first.split("$schema=", 1)[1].strip()
    assert (path.parent / target).resolve().exists(), target


def test_org_example_passes_the_committed_schema_independently() -> None:
    raw = yaml.safe_load(ORG_FILE.read_text(encoding="utf-8"))
    jsonschema.validate(_as_json(raw), _schema("squad-config.schema.json"))


def test_projects_example_passes_the_committed_schema_independently() -> None:
    raw = yaml.safe_load(PROJECTS.read_text(encoding="utf-8"))
    jsonschema.validate(_as_json(raw), _schema("projects.schema.json"))


@pytest.mark.parametrize(
    "path",
    sorted((EXAMPLES / "repo").glob("**/.squad/config.yml")),
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_repo_examples_pass_the_committed_schema_independently(path: Path) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    jsonschema.validate(_as_json(raw), _schema("squad-config.schema.json"))


def _sources() -> ConfigSources:
    return ConfigSources(ORG_FILE, {}, PROJECTS, PROFILES)


@pytest.mark.parametrize(
    ("project", "repo"),
    [
        ("acme/web-app", "repo/react-app/.squad/config.yml"),
        ("platform/payments-api", "repo/java-service/.squad/config.yml"),
        ("acme/web-shop", None),
        ("platform/legacy-api", None),
    ],
)
def test_repo_examples_resolve_without_rejected_layers(
    project: str, repo: str | None
) -> None:
    sources = _sources()
    text = (EXAMPLES / repo).read_text(encoding="utf-8") if repo else None
    effective = resolve(
        project,
        org=load_org(sources),
        registry=load_registry(sources),
        repo_config_text=text,
        call_overrides=None,
    )
    assert effective.rejected_layers == []
    assert not [w for w in effective.warnings if "ignored" in w]


def test_react_example_extends_balanced_and_adds_routes() -> None:
    sources = _sources()
    effective = resolve(
        "acme/web-app",
        org=load_org(sources),
        registry=load_registry(sources),
        repo_config_text=(EXAMPLES / "repo/react-app/.squad/config.yml").read_text(),
        call_overrides=None,
    )
    globs = [route.glob for route in effective.config.routing.routes]
    assert "src/hooks/**" in globs
    assert "**/*.tsx" in globs
    assert effective.provenance["routing.routes"] == "repo"


def test_extra_agent_example_is_routed_by_config() -> None:
    sources = _sources()
    org = load_org(ConfigSources(EXAMPLES / "org/squad.yaml", {}, None, None))
    fragment = yaml.safe_load((ORG / "extra-agents.yaml").read_text(encoding="utf-8"))
    merged = {**org, **fragment}
    effective = resolve(
        "acme/web-shop",
        org=merged,
        registry=load_registry(sources),
        repo_config_text=None,
        call_overrides=None,
    )
    assert [agent.id for agent in effective.config.extra_agents] == ["oscar"]
    assert effective.config.extra_agents[0].tool_preset == "review_publish"
