from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from code_squad._common.fake_model import ScriptedModel, ToolCall, Turn
from code_squad._common.findings import marker
from tests.agents.support import (
    HEAD,
    INJECTION,
    REACT_PATH,
    REACT_TEXT,
    client_for,
    comments_with_marker,
    invoke,
    line_of,
    models,
    react_provider,
    writes_of,
)
from tests.support import finding_dict, finish_turn, tool_result_texts


def _finding(**overrides: Any) -> dict[str, Any]:
    base = finding_dict(
        agent="jim",
        head_sha=HEAD,
        file=REACT_PATH,
        category="security",
        rule_id="REACT-SEC-001",
        severity="blocker",
        confidence="high",
        line_start=line_of(REACT_TEXT, "dangerouslySetInnerHTML"),
        line_end=line_of(REACT_TEXT, "dangerouslySetInnerHTML"),
        title="Unsanitised HTML from the profile bio",
        rationale="The bio is rendered with dangerouslySetInnerHTML unsanitised.",
        failure_scenario="A bio with a script runs in every viewer's session.",
    )
    base.update(overrides)
    return base


def _race_finding() -> dict[str, Any]:
    return _finding(
        rule_id="REACT-HOOKS-001",
        category="correctness",
        severity="major",
        confidence="medium",
        line_start=line_of(REACT_TEXT, "fetchProfile(userId)"),
        line_end=line_of(REACT_TEXT, "fetchProfile(userId)"),
        title="Fetch response can overwrite a newer request",
        rationale="The effect has no cleanup, so a late response replaces newer data.",
        failure_scenario=None,
    )


def _review_script(findings: list[dict[str, Any]], verdict: str) -> list[Turn]:
    """Scripted run: context, one range read, one skill, publish (if any), finish.

    In dry-run the publish call is refused by the gate; the script still makes it so
    the refusal is exercised.
    """
    turns = [
        Turn((ToolCall("get_review_context", {}),)),
        Turn((ToolCall("read_file", {"path": REACT_PATH, "start": 1, "end": 30}),)),
        Turn((ToolCall("load_skill", {"name": "react-conventions"}),)),
    ]
    if findings:
        publish = {"findings": findings, "summary": "Issues found."}
        turns.append(Turn((ToolCall("publish_review", publish),)))
    turns.append(finish_turn(verdict, "Issues found.", findings))
    return turns


def test_dry_run_returns_findings_and_writes_nothing(tmp_path: Path) -> None:
    fake = react_provider()
    model = ScriptedModel(
        _review_script([_finding(), _race_finding()], "request_changes")
    )
    client = client_for("jim", fake, models(model), tmp_path)
    result = invoke(client, post=False)
    assert result["status"] == "complete"
    assert result["verdict"] == "request_changes"
    assert len(result["findings"]) == 2
    assert all(len(item["id"]) == 16 for item in result["findings"])
    assert fake.writes == []
    assert "dry-run blocked 1 external write attempt(s)" in result["warnings"]
    assert result["stats"]["skills_applied"] == ["react-conventions"]
    assert len(result["stats"]["config_hash"]) == 16


def test_review_context_reports_react_version_and_the_skill_index(
    tmp_path: Path,
) -> None:
    fake = react_provider()
    model = ScriptedModel(_review_script([], "approve"))
    client = client_for("jim", fake, models(model), tmp_path)
    invoke(client, post=False)
    texts = tool_result_texts(model.calls[-1].messages)
    context = json.loads(next(t for t in texts if t.lstrip().startswith("{")))
    assert context["frameworks"]["react"] == "^18.3.1"
    assert context["frameworks"]["typescript_strict"] is True
    assert context["change_request"]["head_sha"] == HEAD
    assert [item["path"] for item in context["files"]] == [REACT_PATH]
    assert any("react-conventions" in text for text in texts)


def test_posting_writes_inline_comments_summary_and_status_once(tmp_path: Path) -> None:
    fake = react_provider()
    model = ScriptedModel(
        _review_script([_finding(), _race_finding()], "request_changes")
    )
    client = client_for("jim", fake, models(model), tmp_path)
    result = invoke(client, post=True)
    assert result["status"] == "complete"
    inline = writes_of(fake, "post_inline_comments")
    assert len(inline) == 1 and inline[0]["count"] == 2
    assert len(writes_of(fake, "upsert_comment")) == 1
    statuses = writes_of(fake, "set_status")
    assert len(statuses) == 1
    assert statuses[0]["context"] == "ai-review/jim"
    assert statuses[0]["state"] == "failed"
    assert len(comments_with_marker(fake, "code-squad:summary:jim")) == 1
    assert fake.writes[0][1]["head_sha"] == HEAD


def test_rerunning_the_same_invocation_does_not_duplicate_comments(
    tmp_path: Path,
) -> None:
    fake = react_provider()
    first = ScriptedModel(
        _review_script([_finding(), _race_finding()], "request_changes")
    )
    second = ScriptedModel(
        _review_script([_finding(), _race_finding()], "request_changes")
    )
    client = client_for("jim", fake, models(first, second), tmp_path)
    run_one = invoke(client, post=True)
    run_two = invoke(client, post=True)
    for item in run_one["findings"]:
        assert len(comments_with_marker(fake, marker(item["id"]))) == 1
    assert len(writes_of(fake, "post_inline_comments")) == 1
    assert len(comments_with_marker(fake, "code-squad:summary:jim")) == 1
    assert len(writes_of(fake, "upsert_comment")) == 2
    assert run_two["findings"][0]["id"] == run_one["findings"][0]["id"]


def test_finding_outside_the_changed_lines_is_demoted_to_a_general_note(
    tmp_path: Path,
) -> None:
    fake = react_provider()
    far = _finding(
        rule_id="REACT-COMP-001",
        category="maintainability",
        severity="minor",
        confidence="high",
        line_start=500,
        line_end=500,
        title="Component defined far outside this change",
        rationale="Points at code this change does not touch.",
        failure_scenario=None,
    )
    model = ScriptedModel(_review_script([far], "comment"))
    client = client_for("jim", fake, models(model), tmp_path)
    invoke(client, post=True)
    assert writes_of(fake, "post_inline_comments") == []
    summary = comments_with_marker(fake, "code-squad:summary:jim")[0]
    assert "General notes" in summary
    assert "Component defined far outside this change" in summary
    assert "lines are outside the changed hunks" in summary


def test_injected_instruction_in_the_diff_does_not_change_the_computed_verdict(
    tmp_path: Path,
) -> None:
    fake = react_provider()
    model = ScriptedModel(_review_script([_finding()], "request_changes"))
    client = client_for("jim", fake, models(model), tmp_path)
    result = invoke(client, post=True)
    statuses = writes_of(fake, "set_status")
    assert statuses[0]["state"] == "failed"
    assert result["verdict"] == "request_changes"
    texts = tool_result_texts(model.calls[-1].messages)
    patch_texts = [t for t in texts if INJECTION in t]
    assert patch_texts and all("<untrusted id=" in t for t in patch_texts)
    for item in result["findings"]:
        assert INJECTION not in item["title"] and INJECTION not in item["rationale"]


def test_iteration_limit_yields_an_incomplete_result(tmp_path: Path) -> None:
    fake = react_provider()
    model = ScriptedModel(_review_script([_finding()], "request_changes"))
    org = "agents:\n  jim:\n    max_iterations: 2\n"
    client = client_for("jim", fake, models(model), tmp_path, org=org)
    result = invoke(client, post=True)
    assert result["status"] == "incomplete"
    assert result["verdict"] == "incomplete"
    assert any("iteration limit reached" in w for w in result["warnings"])
    assert fake.writes == []


def test_disabled_jim_is_incomplete_and_the_model_is_never_called(
    tmp_path: Path,
) -> None:
    fake = react_provider()
    calls: list[str] = []

    def _factory(model_id: str, *_args: Any) -> ScriptedModel:
        calls.append(model_id)
        return ScriptedModel([finish_turn()])

    client = client_for(
        "jim", fake, _factory, tmp_path, org="agents:\n  jim:\n    enabled: false\n"
    )
    result = invoke(client, post=True)
    assert calls == []
    assert result["status"] == "incomplete"
    assert "agent disabled by configuration" in result["warnings"]
    assert fake.writes == []


def test_review_targets_the_change_request_in_the_run(tmp_path: Path) -> None:
    fake = react_provider()
    model = ScriptedModel(_review_script([], "approve"))
    client = client_for("jim", fake, models(model), tmp_path)
    invoke(client, post=False)
    first_turn = model.calls[0].messages[0]["content"][0]["text"]
    assert "Review change request 7 in project acme/storefront" in first_turn
