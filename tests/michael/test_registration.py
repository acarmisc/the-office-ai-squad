from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from code_squad._common.config.presets import (
    REVIEW_PUBLISH_TOOLS,
    REVIEW_READONLY_TOOLS,
)
from code_squad._common.config.schema import ExtraAgent
from code_squad._common.registry import (
    ExtraAgentError,
    UnknownAgentError,
    extra_agent_ids,
    extra_knowledge_dirs,
    get_spec,
    register_extra_agents,
)
from code_squad._common.session import MemorySessionStore
from code_squad._common.tool_policy import ToolClass, classify, tool_name
from code_squad.server import create_app
from tests.support import factory_of

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "org" / "extra-agents.yaml"


@pytest.fixture(autouse=True)
def _no_extras_left_behind() -> Iterator[None]:
    yield
    register_extra_agents([])


def _example_oscar(prompt_path: Path) -> ExtraAgent:
    fragment: dict[str, Any] = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    raw = dict(fragment["extra_agents"][0])
    raw["prompt_path"] = str(prompt_path)
    raw["knowledge_dirs"] = [str(prompt_path.parent / "knowledge")]
    return ExtraAgent.model_validate(raw)


def _prompt(tmp_path: Path) -> Path:
    path = tmp_path / "oscar" / "prompt.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Oscar — Python reviewer\n\nReview Python code.\n", encoding="utf-8"
    )
    return path


def test_example_extra_agent_registers_with_its_prompt_and_model(
    tmp_path: Path,
) -> None:
    register_extra_agents([_example_oscar(_prompt(tmp_path))])
    spec = get_spec("oscar")
    assert spec.name == "oscar"
    assert spec.role == "extra"
    assert spec.description.startswith("Python reviewer")
    assert spec.model_id == "sonnet-5-5"
    assert spec.system_prompt.startswith("# Oscar")
    assert extra_agent_ids() == ("oscar",)
    assert extra_knowledge_dirs("oscar") == (str(tmp_path / "oscar" / "knowledge"),)


def test_review_publish_preset_adds_only_publish_review_as_external_write(
    tmp_path: Path,
) -> None:
    register_extra_agents([_example_oscar(_prompt(tmp_path))])
    tools = get_spec("oscar").tools
    names = [tool_name(tool) for tool in tools]
    assert names == list(REVIEW_PUBLISH_TOOLS)
    external = [name for name in names if classify(name) is ToolClass.EXTERNAL_WRITE]
    assert external == ["publish_review"]


def test_review_readonly_preset_has_no_external_write(tmp_path: Path) -> None:
    base = _example_oscar(_prompt(tmp_path))
    readonly = base.model_copy(update={"tool_preset": "review_readonly"})
    register_extra_agents([readonly])
    names = [tool_name(tool) for tool in get_spec("oscar").tools]
    assert names == list(REVIEW_READONLY_TOOLS)
    assert all(classify(name) is not ToolClass.EXTERNAL_WRITE for name in names)


def test_missing_prompt_file_is_a_registration_error(tmp_path: Path) -> None:
    missing = _example_oscar(tmp_path / "nowhere" / "prompt.md")
    with pytest.raises(ExtraAgentError, match="cannot be read"):
        register_extra_agents([missing])


def test_empty_prompt_file_is_a_registration_error(tmp_path: Path) -> None:
    path = _prompt(tmp_path)
    path.write_text("   \n", encoding="utf-8")
    with pytest.raises(ExtraAgentError, match="is empty"):
        register_extra_agents([_example_oscar(path)])


def test_built_in_ids_cannot_be_registered_as_extras(tmp_path: Path) -> None:
    clash = _example_oscar(_prompt(tmp_path)).model_copy(update={"id": "jim"})
    with pytest.raises(ExtraAgentError, match="not unique"):
        register_extra_agents([clash])


def test_duplicate_extra_ids_are_rejected(tmp_path: Path) -> None:
    oscar = _example_oscar(_prompt(tmp_path))
    with pytest.raises(ExtraAgentError, match="not unique"):
        register_extra_agents([oscar, oscar])


def test_unknown_agents_still_raise_after_registration(tmp_path: Path) -> None:
    register_extra_agents([_example_oscar(_prompt(tmp_path))])
    with pytest.raises(UnknownAgentError):
        get_spec("toby")


def test_registration_replaces_the_previous_set(tmp_path: Path) -> None:
    register_extra_agents([_example_oscar(_prompt(tmp_path))])
    register_extra_agents([])
    assert extra_agent_ids() == ()
    with pytest.raises(UnknownAgentError):
        get_spec("oscar")


def test_extra_agent_service_loads_from_the_organisation_config(tmp_path: Path) -> None:
    prompt = _prompt(tmp_path)
    org = tmp_path / "squad.yaml"
    fragment: dict[str, Any] = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    fragment["extra_agents"][0]["prompt_path"] = str(prompt)
    fragment["extra_agents"][0]["knowledge_dirs"] = []
    org.write_text(yaml.safe_dump(fragment), encoding="utf-8")
    from code_squad._common.config.loader import ConfigSources
    from code_squad.michael.gateway import MichaelWiring

    wiring = MichaelWiring(
        env={},
        config_sources=ConfigSources(
            org_file=org, env={}, projects_dir=None, profiles_dir=None
        ),
    )
    app = create_app(
        "oscar",
        model_factory=factory_of(),
        session_store=MemorySessionStore(),
        wiring=wiring,
    )
    client = TestClient(app)
    assert client.get("/ready").json() == {"status": "ready", "agent": "oscar"}


def test_extra_agent_that_cannot_load_reports_not_ready(tmp_path: Path) -> None:
    org = tmp_path / "squad.yaml"
    fragment: dict[str, Any] = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    fragment["extra_agents"][0]["prompt_path"] = str(tmp_path / "missing.md")
    org.write_text(yaml.safe_dump(fragment), encoding="utf-8")
    from code_squad._common.config.loader import ConfigSources
    from code_squad.michael.gateway import MichaelWiring

    wiring = MichaelWiring(
        env={},
        config_sources=ConfigSources(
            org_file=org, env={}, projects_dir=None, profiles_dir=None
        ),
    )
    app = create_app(
        "oscar",
        model_factory=factory_of(),
        session_store=MemorySessionStore(),
        wiring=wiring,
    )
    response = TestClient(app).get("/ready")
    assert response.status_code == 503
    assert response.json()["error"] == "ExtraAgentError"
