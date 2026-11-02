from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from code_squad._common.registry import AGENT_IDS

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog-info.yaml"
SYSTEM = "code-squad"
COMMON_PATHS = {"/invocations", "/ping", "/ready", "/metrics"}
WEBHOOK_PATHS = {"/webhooks/gitlab", "/webhooks/github"}


def _documents() -> list[dict[str, Any]]:
    loaded = [
        doc for doc in yaml.safe_load_all(CATALOG.read_text(encoding="utf-8")) if doc
    ]
    assert all(isinstance(doc, dict) for doc in loaded)
    return loaded


def _of_kind(kind: str) -> list[dict[str, Any]]:
    return [doc for doc in _documents() if doc.get("kind") == kind]


def test_one_system_describes_the_squad() -> None:
    systems = _of_kind("System")
    assert [doc["metadata"]["name"] for doc in systems] == [SYSTEM]
    assert systems[0]["metadata"]["annotations"]["backstage.io/techdocs-ref"] == "dir:."


@pytest.mark.parametrize("agent", AGENT_IDS)
def test_each_agent_has_a_component_and_an_api(agent: str) -> None:
    components = {doc["metadata"]["name"]: doc for doc in _of_kind("Component")}
    apis = {doc["metadata"]["name"]: doc for doc in _of_kind("API")}
    component = components[f"code-squad-{agent}"]
    api_name = f"code-squad-{agent}-api"
    assert api_name in apis

    spec = component["spec"]
    assert spec["type"] == "ai-agent"
    assert spec["system"] == SYSTEM
    assert spec["providesApis"] == [api_name]
    assert component["metadata"]["annotations"]["backstage.io/techdocs-ref"] == "dir:."

    api_spec = apis[api_name]["spec"]
    assert api_spec["type"] == "openapi"
    assert api_spec["system"] == SYSTEM


@pytest.mark.parametrize("agent", AGENT_IDS)
def test_each_api_definition_is_openapi_3_with_the_contract_paths(agent: str) -> None:
    api = next(
        doc
        for doc in _of_kind("API")
        if doc["metadata"]["name"] == f"code-squad-{agent}-api"
    )
    definition = yaml.safe_load(api["spec"]["definition"])
    assert definition["openapi"].startswith("3.")
    paths = set(definition["paths"])
    assert paths >= COMMON_PATHS
    if agent == "michael":
        assert paths >= WEBHOOK_PATHS
    else:
        assert not paths & WEBHOOK_PATHS


def test_catalog_has_no_entities_beyond_the_squad() -> None:
    kinds = {doc.get("kind") for doc in _documents()}
    assert kinds == {"System", "Component", "API"}
    assert len(_of_kind("Component")) == len(AGENT_IDS)
    assert len(_of_kind("API")) == len(AGENT_IDS)


CAPABILITY_CATEGORIES = {
    "reasoning",
    "retrieval",
    "tools",
    "vision",
    "voice",
    "data",
    "safety",
}
HIRE_FIELD_TYPES = {"text", "url", "textarea", "select", "number"}


def _components() -> dict[str, dict[str, Any]]:
    return {doc["metadata"]["name"]: doc for doc in _of_kind("Component")}


@pytest.mark.parametrize("agent", AGENT_IDS)
def test_each_agent_is_visible_to_the_backstage_ai_agents_plugin(agent: str) -> None:
    component = _components()[f"code-squad-{agent}"]
    annotations = component["metadata"]["annotations"]
    prefix = "ai-agent.io/"
    assert annotations[prefix + "runtime"] == "http"
    assert annotations[prefix + "runtime-handle"] == f"code-squad-{agent}"
    assert annotations[prefix + "telemetry-id"] == f"code-squad-{agent}"
    assert annotations[prefix + "squad"] == SYSTEM
    endpoint = annotations[prefix + "endpoint"]
    assert annotations[prefix + "health"] == f"{endpoint}/ping"
    assert not any(key.startswith("ai-agent.acarmisc.org/") for key in annotations)
    for entry in annotations[prefix + "capabilities"].split(","):
        assert entry.partition(":")[2] in CAPABILITY_CATEGORIES


@pytest.mark.parametrize("agent", AGENT_IDS)
def test_hire_form_matches_its_prompt_template(agent: str) -> None:
    annotations = _components()[f"code-squad-{agent}"]["metadata"]["annotations"]
    fields = json.loads(annotations["ai-agent.io/hire-schema"])
    names = {field["name"] for field in fields}
    assert {"project", "action"} <= names
    for field in fields:
        assert field["label"]
        assert field.get("type", "text") in HIRE_FIELD_TYPES
        if field.get("type") == "select":
            assert field["options"]
            assert field.get("default", field["options"][0]) in field["options"]
    placeholders = set(
        re.findall(r"\{(\w+)\}", annotations["ai-agent.io/prompt-template"])
    )
    assert placeholders <= names


def test_the_orchestrator_depends_on_every_specialist() -> None:
    depends_on = _components()["code-squad-michael"]["spec"]["dependsOn"]
    specialists = {
        f"component:default/code-squad-{a}" for a in AGENT_IDS if a != "michael"
    }
    assert set(depends_on) == specialists
