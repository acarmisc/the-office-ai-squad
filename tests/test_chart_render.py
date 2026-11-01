"""Rendered Deployment environment for the webhook providers and the API token."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

CHART: Path = Path(__file__).resolve().parents[1] / "deploy" / "helm" / "code-squad"

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm not installed"
)


def _containers(*sets: str) -> dict[str, dict[str, dict[str, Any]]]:
    command = ["helm", "template", "t", str(CHART), *sets]
    rendered = subprocess.run(command, capture_output=True, text=True, check=True)
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for doc in yaml.safe_load_all(rendered.stdout):
        if not doc or doc.get("kind") != "Deployment":
            continue
        container = doc["spec"]["template"]["spec"]["containers"][0]
        component = doc["metadata"]["labels"]["app.kubernetes.io/component"]
        result[component] = {entry["name"]: entry for entry in container["env"]}
    return result


def test_michael_gets_both_webhook_providers_and_no_one_else() -> None:
    env = _containers()
    assert env["michael"]["WEBHOOK_PROVIDERS"]["value"] == "gitlab,github"
    for agent in ("jim", "angela", "dwight", "darryl", "pam"):
        assert "WEBHOOK_PROVIDERS" not in env[agent]


def test_disabled_providers_are_left_out_of_webhook_providers() -> None:
    env = _containers("--set", "webhooks.github.enabled=false")
    assert env["michael"]["WEBHOOK_PROVIDERS"]["value"] == "gitlab"
    env = _containers(
        "--set",
        "webhooks.gitlab.enabled=false",
        "--set",
        "webhooks.github.enabled=false",
    )
    assert env["michael"]["WEBHOOK_PROVIDERS"]["value"] == ""


def test_api_token_is_a_secret_reference_on_every_agent_when_configured() -> None:
    env = _containers("--set", "api.tokenSecret.name=squad-api")
    for agent, variables in env.items():
        ref = variables["SQUAD_API_TOKEN"]["valueFrom"]["secretKeyRef"]
        assert ref == {"name": "squad-api", "key": "api-token"}, agent


def test_api_token_is_absent_by_default() -> None:
    for variables in _containers().values():
        assert "SQUAD_API_TOKEN" not in variables


def _render_result(*sets: str) -> subprocess.CompletedProcess[str]:
    command = ["helm", "template", "t", str(CHART), *sets]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def test_michael_with_several_replicas_needs_a_shared_session_store() -> None:
    rendered = _render_result("--set", "agents.michael.replicas=2")
    assert rendered.returncode != 0
    assert "sessionStore.url" in rendered.stderr


def test_michael_hpa_needs_a_shared_session_store() -> None:
    rendered = _render_result("--set", "hpa.enabled=true")
    assert rendered.returncode != 0
    assert "sessionStore.url" in rendered.stderr


def test_michael_scales_once_a_session_store_is_configured() -> None:
    rendered = _render_result(
        "--set",
        "agents.michael.replicas=2",
        "--set",
        "sessionStore.url=redis://session-store.example.test:6379",
    )
    assert rendered.returncode == 0, rendered.stderr


def test_the_chart_never_opens_the_api_by_default() -> None:
    for variables in _containers().values():
        assert "SQUAD_ALLOW_UNAUTHENTICATED" not in variables


def test_allow_unauthenticated_is_rendered_on_every_agent_only_when_set() -> None:
    env = _containers("--set", "api.allowUnauthenticated=true")
    for agent, variables in env.items():
        assert variables["SQUAD_ALLOW_UNAUTHENTICATED"]["value"] == "1", agent
    assert (
        "SQUAD_ALLOW_UNAUTHENTICATED"
        not in _containers("--set", "api.allowUnauthenticated=false")["michael"]
    )
