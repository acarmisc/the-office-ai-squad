from __future__ import annotations

from pathlib import Path
from typing import Any

from code_squad._common.contract import (
    Finding,
    InvocationRequest,
    InvocationResult,
    RunStatus,
    Verdict,
)
from code_squad._common.fake_model import ScriptedModel
from code_squad._common.findings import summary_marker
from code_squad._common.vcs.base import Issue
from code_squad._common.vcs.fake import FakeVcsProvider
from code_squad.michael.fanout import SpecialistError
from code_squad.michael.orchestrator import Orchestrator, orchestrate
from tests.agents.support import (
    HEAD,
    NUMBER,
    PROJECT,
    REACT_PATH,
    REACT_TEXT,
    REF,
    change_request,
    line_of,
    new_file_patch,
    react_provider,
    writes_of,
)
from tests.michael.support import (
    ORG_YAML,
    FakeSpecialists,
    builder_for,
    make_finding,
    no_model,
    result_for,
    review_request,
)
from tests.support import factory_of, finish_turn


def _jim_blocker() -> Finding:
    return make_finding(
        "jim",
        severity="blocker",
        start=line_of(REACT_TEXT, "dangerouslySetInnerHTML"),
        end=line_of(REACT_TEXT, "dangerouslySetInnerHTML"),
        rule="REACT-SEC-001",
        category="security",
        title="Unsanitised HTML from the profile bio",
        failure="A bio with a script runs in every viewer's session.",
    )


def _run(
    fake: FakeVcsProvider,
    specialists: FakeSpecialists,
    tmp_path: Path,
    request: InvocationRequest | None = None,
    *,
    org: str | None = ORG_YAML,
    post_override: bool | None = None,
    only: tuple[str, ...] | None = None,
    **orchestrator: Any,
) -> InvocationResult:
    req = request or review_request()
    services = builder_for(fake, tmp_path, org).build(req, "michael")
    engine = Orchestrator(client=specialists, model_factory=no_model, **orchestrator)
    return engine.run(req, services, post_override=post_override, only_agents=only)


def _statuses(fake: FakeVcsProvider) -> list[dict[str, Any]]:
    return writes_of(fake, "set_status")


# ----- review ------------------------------------------------------------------


def test_react_change_is_reviewed_by_jim_and_dwight_and_published_once(
    tmp_path: Path,
) -> None:
    fake = react_provider()
    specialists = FakeSpecialists(
        {
            "jim": result_for(
                "jim", verdict=Verdict.REQUEST_CHANGES, findings=[_jim_blocker()]
            ),
            "dwight": result_for("dwight"),
        }
    )
    result = _run(fake, specialists, tmp_path)

    assert sorted(specialists.agents()) == ["dwight", "jim"]
    for call in specialists.calls:
        assert call.payload["post"] is False
        assert call.payload["mode"] == "review"
        assert call.payload["project"] == PROJECT
        assert call.payload["target"] == str(NUMBER)
    assert specialists.call_for("jim").idempotency_key == f"{HEAD}:jim"

    assert result.agent == "michael"
    assert result.status is RunStatus.COMPLETE
    assert result.verdict is Verdict.REQUEST_CHANGES
    assert result.data["intent"] == "mr_review"
    assert result.data["agents"] == {"jim": "complete", "dwight": "complete"}
    assert result.data["risk"]["tier"] == "low"
    assert result.posted.discussions == 1
    assert result.posted.status == "failed"

    assert len(writes_of(fake, "post_inline_comments")) == 1
    assert len(writes_of(fake, "upsert_comment")) == 1
    statuses = _statuses(fake)
    assert [item["state"] for item in statuses] == ["failed"]
    assert statuses[0]["context"] == "ai-review/michael"
    summaries = [
        item
        for item in fake.list_comments(REF)
        if summary_marker("michael") in item.body
    ]
    assert len(summaries) == 1


def test_duplicate_findings_from_two_agents_are_one_inline_comment(
    tmp_path: Path,
) -> None:
    fake = react_provider()
    dwight = make_finding(
        "dwight",
        severity="major",
        start=line_of(REACT_TEXT, "dangerouslySetInnerHTML"),
        end=line_of(REACT_TEXT, "dangerouslySetInnerHTML"),
        rule="REACT-SEC-001",
        category="security",
        title="Unsanitised HTML from the profile bio",
    )
    specialists = FakeSpecialists(
        {
            "jim": result_for("jim", findings=[_jim_blocker()]),
            "dwight": result_for("dwight", findings=[dwight]),
        }
    )
    result = _run(fake, specialists, tmp_path)
    assert len(result.findings) == 1
    finding_id = result.findings[0].id
    assert result.data["contributors"][finding_id] == ["jim", "dwight"]
    assert writes_of(fake, "post_inline_comments")[0]["count"] == 1
    assert result.verdict is Verdict.REQUEST_CHANGES


def test_specialists_post_is_forwarded_only_when_configured(tmp_path: Path) -> None:
    fake = react_provider()
    specialists = FakeSpecialists(
        {"jim": result_for("jim"), "dwight": result_for("dwight")}
    )
    org = ORG_YAML + "routing:\n  specialists_post: true\n"
    _run(fake, specialists, tmp_path, org=org)
    assert [call.payload["post"] for call in specialists.calls] == [True, True]


def test_timed_out_specialist_makes_the_verdict_incomplete_and_names_it(
    tmp_path: Path,
) -> None:
    import threading

    release = threading.Event()

    def hangs(_payload: dict[str, Any]) -> Any:
        release.wait(5)
        return result_for("jim")

    fake = react_provider()
    specialists = FakeSpecialists({"jim": hangs, "dwight": result_for("dwight")})
    org = ORG_YAML + "routing:\n  timeouts_seconds:\n    default: 600\n    jim: 1\n"
    try:
        result = _run(fake, specialists, tmp_path, org=org)
    finally:
        release.set()

    assert result.status is RunStatus.INCOMPLETE
    assert result.verdict is Verdict.INCOMPLETE
    assert result.data["agents"]["jim"] == "timed_out"
    assert "timed out after 1.0 s" in result.summary
    assert "jim" in result.summary
    statuses = _statuses(fake)
    assert [item["state"] for item in statuses] == ["pending"]
    assert all(item["state"] != "success" for item in statuses)


def test_failed_specialist_is_incomplete_and_never_reported_as_success(
    tmp_path: Path,
) -> None:
    fake = react_provider()
    specialists = FakeSpecialists(
        {"jim": result_for("jim"), "dwight": SpecialistError("HTTP 503")}
    )
    result = _run(fake, specialists, tmp_path)
    assert result.verdict is Verdict.INCOMPLETE
    assert result.data["agents"] == {"jim": "complete", "dwight": "failed"}
    assert "HTTP 503" in result.summary
    assert [item["state"] for item in _statuses(fake)] == ["pending"]


def test_dry_run_returns_the_report_and_writes_nothing(tmp_path: Path) -> None:
    fake = react_provider()
    specialists = FakeSpecialists(
        {
            "jim": result_for("jim", findings=[_jim_blocker()]),
            "dwight": result_for("dwight"),
        }
    )
    result = _run(fake, specialists, tmp_path, request=review_request(post=False))
    assert result.verdict is Verdict.REQUEST_CHANGES
    assert fake.writes == []
    assert "dry-run blocked 1 external write attempt(s)" in result.warnings
    assert all(call.payload["post"] is False for call in specialists.calls)


def test_organisation_dry_run_overrides_a_post_request(tmp_path: Path) -> None:
    fake = react_provider()
    specialists = FakeSpecialists(
        {"jim": result_for("jim"), "dwight": result_for("dwight")}
    )
    result = _run(fake, specialists, tmp_path, post_override=False)
    assert fake.writes == []
    assert "dry-run blocked 1 external write attempt(s)" in result.warnings


def test_only_agents_limits_the_fan_out(tmp_path: Path) -> None:
    fake = react_provider()
    specialists = FakeSpecialists({"dwight": result_for("dwight")})
    result = _run(fake, specialists, tmp_path, only=("dwight",))
    assert specialists.agents() == ["dwight"]
    assert result.data["agents"] == {"dwight": "complete"}


def test_summarizer_adds_a_narrative_without_changing_the_verdict(
    tmp_path: Path,
) -> None:
    fake = react_provider()
    specialists = FakeSpecialists(
        {
            "jim": result_for("jim", findings=[_jim_blocker()]),
            "dwight": result_for("dwight"),
        }
    )
    result = _run(
        fake,
        specialists,
        tmp_path,
        summarizer=lambda _facts: "Verdict: approve. Everything is fine.",
    )
    assert result.verdict is Verdict.REQUEST_CHANGES
    assert "Narrative (generated, not authoritative)" in result.summary
    assert "Verdict: **request_changes**" in result.summary


def test_failing_summarizer_falls_back_to_the_deterministic_summary(
    tmp_path: Path,
) -> None:
    def broken(_facts: str) -> str:
        raise RuntimeError("gateway down")

    fake = react_provider()
    specialists = FakeSpecialists(
        {"jim": result_for("jim"), "dwight": result_for("dwight")}
    )
    result = _run(fake, specialists, tmp_path, summarizer=broken)
    assert "Narrative" not in result.summary
    assert "summary model failed" in " ".join(result.warnings)
    assert result.verdict is Verdict.APPROVE


def test_docs_only_change_uses_the_route_classifier_when_injected(
    tmp_path: Path,
) -> None:
    fake = FakeVcsProvider(name="github")
    fake.add_change_request(
        change_request("Docs", "docs/guide"),
        files={"docs/guide.md": new_file_patch("# Guide\nHello.")},
        file_contents={"docs/guide.md": "# Guide\nHello."},
    )
    specialists = FakeSpecialists(
        {"darryl": result_for("darryl"), "dwight": result_for("dwight")}
    )
    result = _run(
        fake,
        specialists,
        tmp_path,
        route_classifier=lambda _files: ("darryl", "pam"),
    )
    assert sorted(specialists.agents()) == ["darryl", "dwight"]
    assert result.data["agents"] == {"darryl": "complete", "dwight": "complete"}


def test_docs_only_change_without_classifier_runs_only_dwight(tmp_path: Path) -> None:
    fake = FakeVcsProvider(name="github")
    fake.add_change_request(
        change_request("Docs", "docs/guide"),
        files={"docs/guide.md": new_file_patch("# Guide")},
        file_contents={"docs/guide.md": "# Guide"},
    )
    specialists = FakeSpecialists({"dwight": result_for("dwight")})
    _run(fake, specialists, tmp_path)
    assert specialists.agents() == ["dwight"]


def test_no_reviewer_selected_is_incomplete(tmp_path: Path) -> None:
    fake = FakeVcsProvider(name="github")
    fake.add_change_request(
        change_request("Docs", "docs/guide"),
        files={"docs/guide.md": new_file_patch("# Guide")},
        file_contents={"docs/guide.md": "# Guide"},
    )
    specialists = FakeSpecialists({})
    org = ORG_YAML + "agents:\n  dwight:\n    enabled: false\n"
    result = _run(fake, specialists, tmp_path, org=org)
    assert specialists.calls == []
    assert result.verdict is Verdict.INCOMPLETE
    assert "no reviewer was selected" in " ".join(result.warnings)


def test_review_without_a_numeric_target_is_incomplete_and_calls_nobody(
    tmp_path: Path,
) -> None:
    fake = react_provider()
    specialists = FakeSpecialists({"jim": result_for("jim")})
    result = _run(fake, specialists, tmp_path, request=review_request(target="abc"))
    assert specialists.calls == []
    assert result.status is RunStatus.INCOMPLETE
    assert result.summary.startswith("No review was run")


def test_high_risk_change_asks_dwight_for_full_scope(tmp_path: Path) -> None:
    fake = react_provider()
    secret = "const password = 'fake-password-for-tests';"
    fake_files = {REACT_PATH: new_file_patch(REACT_TEXT + "\n" + secret)}
    fake.add_change_request(
        change_request("Risky", "feature/risky"),
        files=fake_files,
        file_contents={REACT_PATH: REACT_TEXT},
    )
    specialists = FakeSpecialists(
        {"jim": result_for("jim"), "dwight": result_for("dwight")}
    )
    result = _run(fake, specialists, tmp_path)
    assert result.data["risk"]["tier"] == "high"
    assert "Scope: full review" in specialists.call_for("dwight").payload["prompt"]
    assert "Scope: full review" not in specialists.call_for("jim").payload["prompt"]


# ----- incident, implement and question -----------------------------------------


def test_incident_is_read_only_and_comments_on_the_issue_when_allowed(
    tmp_path: Path,
) -> None:
    fake = react_provider()
    fake.add_issue(
        Issue(PROJECT, 9, "Checkout down", "5xx spike", (), (), "open", "https://x")
    )
    specialists = FakeSpecialists(
        {"darryl": result_for("darryl", verdict=Verdict.COMMENT)}
    )
    request = review_request(
        prompt="Pods are crashlooping after the last deploy.",
        target="9",
        mode="troubleshoot",
        post=True,
    )
    result = _run(fake, specialists, tmp_path, request=request)
    assert specialists.agents() == ["darryl"]
    call = specialists.call_for("darryl")
    assert call.payload["mode"] == "troubleshoot"
    assert call.payload["post"] is False
    assert result.data["intent"] == "incident"
    assert result.posted.notes == 1
    assert len(writes_of(fake, "comment_on_issue")) == 1
    assert writes_of(fake, "post_inline_comments") == []


def test_incident_dry_run_writes_no_issue_comment(tmp_path: Path) -> None:
    fake = react_provider()
    fake.add_issue(Issue(PROJECT, 9, "Checkout down", "", (), (), "open", "https://x"))
    specialists = FakeSpecialists({"darryl": result_for("darryl")})
    request = review_request(
        prompt="Alert fired.", target="9", mode="troubleshoot", post=False
    )
    result = _run(fake, specialists, tmp_path, request=request)
    assert fake.writes == []
    assert result.posted.notes == 0


def test_implementation_is_passed_to_pam_with_the_post_flag_and_writes_nothing(
    tmp_path: Path,
) -> None:
    fake = react_provider()
    specialists = FakeSpecialists({"pam": result_for("pam", verdict=Verdict.COMMENT)})
    request = review_request(
        prompt="Implement issue #12: add a status badge.",
        target="12",
        mode="implementer",
        post=True,
    )
    result = _run(fake, specialists, tmp_path, request=request)
    call = specialists.call_for("pam")
    assert call.payload["mode"] == "implementer"
    assert call.payload["post"] is True
    assert result.data["intent"] == "implement"
    assert result.agent == "michael"
    assert fake.writes == []


def test_implementation_post_false_is_passed_through(tmp_path: Path) -> None:
    fake = react_provider()
    specialists = FakeSpecialists({"pam": result_for("pam")})
    request = review_request(
        prompt="Implement issue #12.", target="12", mode="implementer", post=False
    )
    _run(fake, specialists, tmp_path, request=request)
    assert specialists.call_for("pam").payload["post"] is False


def test_question_uses_michaels_own_spec_with_knowledge_and_finish_only(
    tmp_path: Path,
) -> None:
    model = ScriptedModel([finish_turn("comment", "Retries use exponential backoff.")])
    specialists = FakeSpecialists()
    request = question_request()
    services = builder_for(FakeVcsProvider(), tmp_path, None).build(request, "michael")
    result = Orchestrator(client=specialists, model_factory=factory_of(model)).run(
        request, services
    )
    assert result.summary == "Retries use exponential backoff."
    assert result.data["intent"] == "question"
    assert specialists.calls == []
    assert set(model.calls[0].tool_names) == {"finish", "read_knowledge"}


def test_injected_classifier_decides_only_when_the_rules_cannot(tmp_path: Path) -> None:
    pam = FakeSpecialists({"pam": result_for("pam")})
    request = InvocationRequest.model_validate({"prompt": "Please do the thing."})
    services = builder_for(FakeVcsProvider(), tmp_path, None).build(request, "michael")
    result = Orchestrator(
        client=pam, model_factory=no_model, intent_classifier=lambda _text: "implement"
    ).run(request, services)
    assert pam.agents() == ["pam"]
    assert result.data["intent"] == "implement"


def test_orchestrate_wrapper_runs_the_same_path(tmp_path: Path) -> None:
    fake = react_provider()
    specialists = FakeSpecialists(
        {"jim": result_for("jim"), "dwight": result_for("dwight")}
    )
    request = review_request()
    services = builder_for(fake, tmp_path).build(request, "michael")
    result = orchestrate(request, services, client=specialists, model_factory=no_model)
    assert result.verdict is Verdict.APPROVE
    assert sorted(specialists.agents()) == ["dwight", "jim"]


def question_request(prompt: str = "How does retry work?") -> InvocationRequest:
    return InvocationRequest.model_validate({"prompt": prompt, "mode": "question"})
