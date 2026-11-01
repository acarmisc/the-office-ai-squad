"""Read-only guarantees for darryl: source scan, tool classes, SPEC shape and prompt."""

from __future__ import annotations

from pathlib import Path

import pytest
from kubernetes.config.config_exception import ConfigException

import code_squad.darryl as darryl_pkg
from code_squad._common.config.schema import OpsConfig
from code_squad._common.tool_policy import ToolClass, classify, tool_name
from code_squad.darryl import SPEC
from code_squad.darryl.k8s import ClusterReader
from code_squad.darryl.observability_adapters import (
    ArgoCdAdapter,
    LokiAdapter,
    PrometheusAdapter,
)
from code_squad.darryl.services import CLUSTER_WARNING, build_ops_services
from code_squad.darryl.tools import TROUBLESHOOT_TOOLS

DARRYL_DIR = Path(darryl_pkg.__file__).resolve().parent
MUTATING_VERBS = ("create_namespaced", "patch_", "delete_", "replace_", "connect_")
MAX_PROMPT_WORDS = 2500


def test_darryl_source_contains_no_mutating_kubernetes_call() -> None:
    sources = sorted(DARRYL_DIR.rglob("*.py"))
    assert sources
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for verb in MUTATING_VERBS:
            assert verb not in text, f"{path.name} contains '{verb}'"


def test_reader_has_no_mutating_method_at_runtime() -> None:
    public = [name for name in dir(ClusterReader) if not name.startswith("_")]
    for name in public:
        assert not name.startswith(("create", "patch", "delete", "replace", "connect"))


def test_only_publish_review_is_an_external_write() -> None:
    writes = [
        tool_name(item)
        for item in SPEC.tools
        if classify(tool_name(item)) is ToolClass.EXTERNAL_WRITE
    ]
    assert writes == ["publish_review"]


def test_no_darryl_tool_is_a_local_mutation() -> None:
    for item in SPEC.tools:
        assert classify(tool_name(item)) is not ToolClass.LOCAL_MUTATION


def test_every_troubleshooting_tool_is_read_only() -> None:
    names = [tool_name(item) for item in TROUBLESHOOT_TOOLS]
    assert len(names) == 12
    assert {classify(name) for name in names} == {ToolClass.READ}


def test_spec_declares_both_modes_and_the_iteration_budget() -> None:
    assert SPEC.name == "darryl"
    assert SPEC.role == "devops"
    assert SPEC.modes == ("review", "troubleshoot")
    assert SPEC.max_iterations == 30
    assert SPEC.task_template == "Mode: {action}. Project: {project}. Target: {target}."
    assert SPEC.render_task("42", "troubleshoot", "acme/web") == (
        "Mode: troubleshoot. Project: acme/web. Target: 42."
    )


def test_spec_tools_include_review_and_troubleshooting_sets() -> None:
    names = {tool_name(item) for item in SPEC.tools}
    for required in (
        "finish",
        "read_knowledge",
        "get_review_context",
        "read_file",
        "search_repo",
        "list_tree",
        "get_project_skills",
        "load_skill",
        "publish_review",
        "k8s_get",
        "k8s_describe",
        "k8s_events",
        "k8s_logs",
        "k8s_top",
        "rollout_history",
        "ci_runs",
        "ci_job_log",
        "prom_query",
        "logs_query",
        "deployment_status",
        "recent_changes",
    ):
        assert required in names, required


def test_prompt_is_within_budget_and_names_the_method() -> None:
    text = (DARRYL_DIR / "prompt.md").read_text(encoding="utf-8")
    assert len(text.split()) < MAX_PROMPT_WORDS
    for phrase in (
        "### Review mode",
        "### Troubleshoot mode",
        "Restate the symptom",
        "List what was not checked",
        '`verdict="comment"`',
        "devops/k8s-failure-patterns",
    ):
        assert phrase in text, phrase


def test_build_services_omits_everything_when_nothing_is_configured() -> None:
    services = build_ops_services(None, env={})
    assert services == {"ops_config": None}


def test_build_services_wires_configured_backends() -> None:
    ops = OpsConfig(
        prometheus_url="https://prom.example.test",
        loki_url="https://loki.example.test",
        argocd_url="https://argocd.example.test",
        max_query_points=500,
    )
    services = build_ops_services(ops, env={})
    assert isinstance(services["metrics"], PrometheusAdapter)
    assert isinstance(services["logs_backend"], LokiAdapter)
    assert isinstance(services["deploy_status"], ArgoCdAdapter)
    assert "cluster" not in services


def test_cluster_is_built_only_inside_a_pod_and_failures_become_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _no_config() -> None:
        raise ConfigException("not in cluster")

    monkeypatch.setattr("kubernetes.config.load_incluster_config", _no_config)
    services = build_ops_services(
        OpsConfig(allowed_namespaces=["shop"]),
        env={"KUBERNETES_SERVICE_HOST": "10.0.0.1"},
    )
    assert "cluster" not in services
    warnings = services["config_warnings"]
    assert isinstance(warnings, list)
    assert warnings[0].startswith(CLUSTER_WARNING)


def test_cluster_reader_is_built_from_in_cluster_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kubernetes.config.load_incluster_config", lambda: None)
    services = build_ops_services(
        OpsConfig(allowed_namespaces=["shop"]),
        env={"KUBERNETES_SERVICE_HOST": "10.0.0.1"},
    )
    assert isinstance(services["cluster"], ClusterReader)
    assert "config_warnings" not in services
