from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from code_squad._common.fake_model import ScriptedModel, ToolCall, Turn
from code_squad._common.findings import marker
from tests.agents.support import (
    HEAD,
    INJECTION,
    JAVA_PATH,
    JAVA_TEXT,
    client_for,
    comments_with_marker,
    invoke,
    java_provider,
    line_of,
    models,
    writes_of,
)
from tests.support import finding_dict, finish_turn, tool_result_texts


def _finding(**overrides: Any) -> dict[str, Any]:
    base = finding_dict(
        agent="angela",
        head_sha=HEAD,
        file=JAVA_PATH,
        category="security",
        rule_id="JAVA-JPA-001",
        severity="blocker",
        confidence="high",
        line_start=line_of(JAVA_TEXT, "createQuery"),
        line_end=line_of(JAVA_TEXT, "createQuery"),
        title="JPQL built by concatenating a request parameter",
        rationale="The status parameter is concatenated into the query text.",
        failure_scenario="A status value containing a quote changes the query.",
        references=["CWE-89"],
    )
    base.update(overrides)
    return base


def _self_call_finding() -> dict[str, Any]:
    return _finding(
        rule_id="JAVA-SPRING-001",
        category="correctness",
        severity="major",
        confidence="high",
        line_start=line_of(JAVA_TEXT, "this.cancel(id)"),
        line_end=line_of(JAVA_TEXT, "this.cancel(id)"),
        title="@Transactional is bypassed by self-invocation",
        rationale="cancelAll is not transactional and calls cancel through this, "
        "so the proxy never starts the transaction.",
        failure_scenario=None,
        references=[],
    )


def _script(findings: list[dict[str, Any]], verdict: str) -> list[Turn]:
    turns = [
        Turn((ToolCall("get_review_context", {}),)),
        Turn((ToolCall("read_knowledge", {"topic": "java/build-hygiene"}),)),
        Turn((ToolCall("read_file", {"path": "pom.xml", "start": 1, "end": 20}),)),
        Turn((ToolCall("read_knowledge", {"topic": "java/spring-core"}),)),
    ]
    if findings:
        turns.append(
            Turn(
                (
                    ToolCall(
                        "publish_review", {"findings": findings, "summary": "Found."}
                    ),
                )
            )
        )
    turns.append(finish_turn(verdict, "Found issues.", findings))
    return turns


def test_dry_run_returns_findings_and_writes_nothing(tmp_path: Path) -> None:
    fake = java_provider()
    model = ScriptedModel(
        _script([_finding(), _self_call_finding()], "request_changes")
    )
    client = client_for("angela", fake, models(model), tmp_path)
    result = invoke(client, post=False)
    assert result["status"] == "complete"
    assert result["verdict"] == "request_changes"
    assert [item["rule_id"] for item in result["findings"]] == [
        "JAVA-JPA-001",
        "JAVA-SPRING-001",
    ]
    assert fake.writes == []
    assert "dry-run blocked 1 external write attempt(s)" in result["warnings"]


def test_review_context_reports_the_java_release_and_knowledge_is_readable(
    tmp_path: Path,
) -> None:
    fake = java_provider()
    model = ScriptedModel(_script([], "approve"))
    client = client_for("angela", fake, models(model), tmp_path)
    invoke(client, post=False)
    texts = tool_result_texts(model.calls[-1].messages)
    context, _end = json.JSONDecoder().raw_decode(
        next(t for t in texts if t.lstrip().startswith("{")).lstrip()
    )
    assert context["frameworks"]["java_release"] == "17"
    assert context["frameworks"]["react"] is None
    assert [item["path"] for item in context["files"]] == [JAVA_PATH]
    assert any("title: Spring core" in t for t in texts)


def test_posting_writes_inline_comments_summary_and_status_once(tmp_path: Path) -> None:
    fake = java_provider()
    model = ScriptedModel(
        _script([_finding(), _self_call_finding()], "request_changes")
    )
    client = client_for("angela", fake, models(model), tmp_path)
    result = invoke(client, post=True)
    assert result["status"] == "complete"
    inline = writes_of(fake, "post_inline_comments")
    assert len(inline) == 1 and inline[0]["count"] == 2
    assert len(writes_of(fake, "upsert_comment")) == 1
    statuses = writes_of(fake, "set_status")
    assert len(statuses) == 1
    assert statuses[0]["context"] == "ai-review/angela"
    assert statuses[0]["state"] == "failed"


def test_rerunning_the_same_invocation_does_not_duplicate_comments(
    tmp_path: Path,
) -> None:
    fake = java_provider()
    first = ScriptedModel(
        _script([_finding(), _self_call_finding()], "request_changes")
    )
    second = ScriptedModel(
        _script([_finding(), _self_call_finding()], "request_changes")
    )
    client = client_for("angela", fake, models(first, second), tmp_path)
    run_one = invoke(client, post=True)
    invoke(client, post=True)
    for item in run_one["findings"]:
        assert len(comments_with_marker(fake, marker(item["id"]))) == 1
    assert len(writes_of(fake, "post_inline_comments")) == 1
    assert len(comments_with_marker(fake, "code-squad:summary:angela")) == 1


def test_finding_outside_the_changed_lines_is_demoted_to_a_general_note(
    tmp_path: Path,
) -> None:
    fake = java_provider()
    far = _finding(
        rule_id="JAVA-PERF-001",
        category="performance",
        severity="minor",
        confidence="medium",
        line_start=900,
        line_end=900,
        title="Regex compiled per call far below this change",
        rationale="Points at a line this change does not add.",
        failure_scenario=None,
        references=[],
    )
    model = ScriptedModel(_script([far], "comment"))
    client = client_for("angela", fake, models(model), tmp_path)
    invoke(client, post=True)
    assert writes_of(fake, "post_inline_comments") == []
    summary = comments_with_marker(fake, "code-squad:summary:angela")[0]
    assert "Regex compiled per call far below this change" in summary
    assert "lines are not added lines" in summary


def test_injected_instruction_in_the_diff_does_not_change_the_computed_verdict(
    tmp_path: Path,
) -> None:
    fake = java_provider()
    model = ScriptedModel(_script([_finding()], "request_changes"))
    client = client_for("angela", fake, models(model), tmp_path)
    result = invoke(client, post=True)
    assert writes_of(fake, "set_status")[0]["state"] == "failed"
    assert result["verdict"] == "request_changes"
    texts = tool_result_texts(model.calls[-1].messages)
    assert any(INJECTION in t and "<untrusted id=" in t for t in texts)
    for item in result["findings"]:
        assert INJECTION not in item["title"] and INJECTION not in item["rationale"]


def test_iteration_limit_yields_an_incomplete_result(tmp_path: Path) -> None:
    fake = java_provider()
    model = ScriptedModel(_script([_finding()], "request_changes"))
    org = "agents:\n  angela:\n    max_iterations: 2\n"
    client = client_for("angela", fake, models(model), tmp_path, org=org)
    result = invoke(client, post=True)
    assert result["status"] == "incomplete"
    assert result["verdict"] == "incomplete"
    assert any("iteration limit reached" in w for w in result["warnings"])
    assert fake.writes == []


def test_angela_reads_only_its_own_pack_and_the_shared_pack(tmp_path: Path) -> None:
    fake = java_provider()
    model = ScriptedModel(
        [
            Turn((ToolCall("read_knowledge", {"topic": "react/index"}),)),
            Turn((ToolCall("read_knowledge", {"topic": "../etc/passwd"}),)),
            finish_turn(),
        ]
    )
    client = client_for("angela", fake, models(model), tmp_path)
    invoke(client, post=False)
    texts = tool_result_texts(model.calls[-1].messages)
    assert any("React knowledge pack index" in t for t in texts)
    assert "invalid topic name" in texts
