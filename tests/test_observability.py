from __future__ import annotations

import json
import logging

import pytest

from code_squad._common.contract import (
    Confidence,
    Finding,
    InvocationResult,
    RunStatus,
    Severity,
    Stats,
    Verdict,
)
from code_squad._common.observability import (
    REGISTRY,
    JsonFormatter,
    record_result,
    span,
)


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _record(agent: str, status: RunStatus = RunStatus.COMPLETE) -> InvocationResult:
    finding = Finding(
        agent=agent,
        rule_id="R1",
        category="correctness",
        severity=Severity.MAJOR,
        confidence=Confidence.HIGH,
        file="a.py",
        line_start=1,
        line_end=1,
        head_sha="sha",
        title="t",
        rationale="r",
    )
    return InvocationResult(
        agent=agent,
        status=status,
        verdict=Verdict.COMMENT,
        summary="s",
        findings=[finding],
        stats=Stats(
            iterations=3,
            input_tokens=100,
            output_tokens=20,
            tool_calls={"finish": 1, "not_a_real_tool": 5},
        ),
    )


def test_record_result_updates_counters_histograms_and_labels() -> None:
    agent = "obs-record-test"
    before_inv = _sample(
        "squad_invocations_total", {"agent": agent, "status": "complete"}
    )
    before_tokens = _sample("squad_tokens_total", {"agent": agent, "kind": "input"})
    before_findings = _sample(
        "squad_findings_total", {"agent": agent, "severity": "major"}
    )
    record_result(_record(agent), 0.25)
    assert (
        _sample("squad_invocations_total", {"agent": agent, "status": "complete"})
        == before_inv + 1
    )
    assert (
        _sample("squad_tokens_total", {"agent": agent, "kind": "input"})
        == before_tokens + 100
    )
    assert (
        _sample("squad_findings_total", {"agent": agent, "severity": "major"})
        == before_findings + 1
    )
    assert _sample("squad_iterations_count", {"agent": agent}) >= 1
    assert _sample("squad_invocation_seconds_count", {"agent": agent}) >= 1


def test_unclassified_tool_names_never_become_metric_labels() -> None:
    agent = "obs-tool-test"
    record_result(_record(agent), 0.1)
    assert (
        _sample(
            "squad_tool_calls_total",
            {"agent": agent, "tool": "finish", "tool_class": "read"},
        )
        >= 1
    )
    assert (
        REGISTRY.get_sample_value(
            "squad_tool_calls_total",
            {"agent": agent, "tool": "not_a_real_tool", "tool_class": "read"},
        )
        is None
    )


def test_metrics_exposition_contains_required_families() -> None:
    from prometheus_client import generate_latest

    record_result(_record("obs-expo-test"), 0.1)
    text = generate_latest(REGISTRY).decode("utf-8")
    for family in (
        "squad_invocations_total",
        "squad_invocation_seconds",
        "squad_iterations",
        "squad_tokens_total",
        "squad_tool_calls_total",
        "squad_findings_total",
        "squad_dry_run_total",
        "squad_cve_cache_hits_total",
        "squad_config_reload_failures_total",
        "squad_vcs_errors_total",
    ):
        assert family in text, family


def test_json_formatter_emits_whitelisted_fields_only() -> None:
    record = logging.makeLogRecord(
        {
            "name": "code_squad.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "invocation finished",
            "agent": "jim",
            "status": "complete",
            "prompt": "PRIVATE PROMPT TEXT",
            "diff": "PRIVATE DIFF",
        }
    )
    entry = json.loads(JsonFormatter().format(record))
    assert entry["msg"] == "invocation finished"
    assert entry["agent"] == "jim"
    assert entry["status"] == "complete"
    assert set(entry) == {"ts", "level", "logger", "msg", "agent", "status"}
    assert "PRIVATE" not in json.dumps(entry)


def test_span_accepts_metadata_attributes() -> None:
    with span("invocation", agent="jim", invocation_id="abc", iterations=2) as current:
        assert current is not None


def test_span_refuses_content_attributes() -> None:
    with pytest.raises(ValueError, match="prompt"), span("invocation", prompt="secret"):
        pass


def test_michael_does_not_count_specialist_usage_twice() -> None:
    agent = "michael"
    before_tokens = _sample("squad_tokens_total", {"agent": agent, "kind": "input"})
    before_findings = _sample(
        "squad_findings_total", {"agent": agent, "severity": "major"}
    )
    before_inv = _sample(
        "squad_invocations_total", {"agent": agent, "status": "complete"}
    )
    result = _record(agent).model_copy(update={"data": {"intent": "mr_review"}})
    record_result(result, 0.1)
    assert (
        _sample("squad_tokens_total", {"agent": agent, "kind": "input"})
        == before_tokens
    )
    assert (
        _sample("squad_findings_total", {"agent": agent, "severity": "major"})
        == before_findings
    )
    assert (
        _sample("squad_invocations_total", {"agent": agent, "status": "complete"})
        == before_inv + 1
    )


def test_michael_question_counts_its_own_usage() -> None:
    agent = "michael"
    before = _sample("squad_tokens_total", {"agent": agent, "kind": "input"})
    result = _record(agent).model_copy(update={"data": {"intent": "question"}})
    record_result(result, 0.1)
    assert (
        _sample("squad_tokens_total", {"agent": agent, "kind": "input"}) == before + 100
    )
