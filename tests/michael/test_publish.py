from __future__ import annotations

from code_squad._common.contract import Finding, Verdict
from code_squad._common.findings import CommentStyle, PublishOptions, summary_marker
from code_squad._common.posting import PostingGate
from code_squad._common.vcs.base import ApproveMode
from code_squad._common.vcs.fake import FakeVcsProvider
from code_squad.michael.aggregate import ConsolidatedReport
from code_squad.michael.publish import DEFAULT_CONTEXT, publish_consolidated
from code_squad.michael.risk import RiskAssessment
from tests.agents.support import (
    HEAD,
    PROJECT,
    REACT_TEXT,
    REF,
    line_of,
    react_provider,
    writes_of,
)
from tests.michael.support import make_finding

SUMMARY = f"### Review by `michael`\n\nVerdict.\n\n{summary_marker('michael')}"


def _blocker() -> Finding:
    return make_finding(
        "jim",
        severity="blocker",
        start=line_of(REACT_TEXT, "dangerouslySetInnerHTML"),
        end=line_of(REACT_TEXT, "dangerouslySetInnerHTML"),
        rule="REACT-SEC-001",
        category="security",
        confidence="high",
        title="Unsanitised HTML from the profile bio",
        failure="A bio with a script runs in every viewer's session.",
    )


def _report(
    verdict: Verdict,
    findings: tuple[Finding, ...] = (),
    failed: dict[str, str] | None = None,
) -> ConsolidatedReport:
    return ConsolidatedReport(
        verdict=verdict,
        findings=findings,
        contributors={item.id: (item.agent,) for item in findings},
        statuses={"jim": "complete", "angela": "failed" if failed else "complete"},
        failed=failed or {},
        risk=RiskAssessment("low", (), 3),
        head_sha=HEAD,
        warnings=(),
    )


def _options(
    comment_style: CommentStyle = "both",
    approve_mode: ApproveMode = "none",
) -> PublishOptions:
    return PublishOptions(
        comment_style=comment_style,
        approve_mode=approve_mode,
        status_context=DEFAULT_CONTEXT,
    )


def _publish(
    fake: FakeVcsProvider,
    report: ConsolidatedReport,
    *,
    gate: PostingGate | None = None,
    options: PublishOptions | None = None,
) -> None:
    publish_consolidated(
        fake,
        REF,
        report,
        SUMMARY,
        gate=gate or PostingGate(post_allowed=True),
        options=options or _options(),
    )


def _statuses(fake: FakeVcsProvider) -> list[dict[str, object]]:
    return writes_of(fake, "set_status")


def test_a_complete_blocking_review_is_published_once_with_one_status() -> None:
    fake = react_provider()
    _publish(fake, _report(Verdict.REQUEST_CHANGES, (_blocker(),)))
    inline = writes_of(fake, "post_inline_comments")
    assert len(inline) == 1 and inline[0]["count"] == 1
    assert len(writes_of(fake, "upsert_comment")) == 1
    statuses = _statuses(fake)
    assert len(statuses) == 1
    assert statuses[0]["state"] == "failed"
    assert statuses[0]["context"] == "ai-review/michael"
    assert statuses[0]["sha"] == HEAD


def test_inline_body_names_the_contributing_agents_and_keeps_the_marker() -> None:
    fake = react_provider()
    _publish(fake, _report(Verdict.REQUEST_CHANGES, (_blocker(),)))
    body = next(
        item.body for item in fake.list_comments(REF) if "Reported by" in item.body
    )
    assert body.startswith("Reported by: jim")
    assert "Unsanitised HTML from the profile bio" in body
    assert "<!-- code-squad:" in body


def test_incomplete_review_is_published_as_pending_and_never_as_success() -> None:
    fake = react_provider()
    report = _report(Verdict.INCOMPLETE, failed={"angela": "timed out after 600 s"})
    _publish(fake, report)
    statuses = _statuses(fake)
    assert [item["state"] for item in statuses] == ["pending"]
    assert "angela" in str(statuses[0]["description"])
    assert all(item["state"] != "success" for item in statuses)


def test_incomplete_review_still_publishes_its_summary_for_the_humans() -> None:
    fake = react_provider()
    _publish(fake, _report(Verdict.INCOMPLETE, failed={"angela": "HTTP 503"}))
    summaries = [
        item
        for item in fake.list_comments(REF)
        if summary_marker("michael") in item.body
    ]
    assert len(summaries) == 1


def test_dry_run_performs_no_writes_and_records_the_blocked_attempt() -> None:
    fake = react_provider()
    gate = PostingGate(post_allowed=False)
    _publish(fake, _report(Verdict.REQUEST_CHANGES, (_blocker(),)), gate=gate)
    assert fake.writes == []
    assert gate.blocked == ["publish_review"]


def test_moved_head_publishes_pending_stale_and_no_findings() -> None:
    fake = react_provider()
    fake.set_head(REF, "e" * 40)
    outcome = publish_consolidated(
        fake,
        REF,
        _report(Verdict.REQUEST_CHANGES, (_blocker(),)),
        SUMMARY,
        gate=PostingGate(post_allowed=True),
        options=_options(),
    )
    assert outcome.posted.status == "pending"
    assert any("head moved" in item for item in outcome.warnings)
    assert writes_of(fake, "post_inline_comments") == []
    assert writes_of(fake, "upsert_comment") == []


def test_republishing_the_same_review_does_not_duplicate_inline_comments() -> None:
    fake: FakeVcsProvider = react_provider()
    report = _report(Verdict.REQUEST_CHANGES, (_blocker(),))
    _publish(fake, report)
    _publish(fake, report)
    assert len(writes_of(fake, "post_inline_comments")) == 1
    summaries = [
        item
        for item in fake.list_comments(REF)
        if summary_marker("michael") in item.body
    ]
    assert len(summaries) == 1


def test_summary_style_posts_no_inline_comments() -> None:
    fake = react_provider()
    _publish(
        fake,
        _report(Verdict.REQUEST_CHANGES, (_blocker(),)),
        options=_options(comment_style="summary"),
    )
    assert writes_of(fake, "post_inline_comments") == []
    assert len(writes_of(fake, "upsert_comment")) == 1


def test_formal_approval_is_submitted_only_when_configured_and_approving() -> None:
    fake = react_provider()
    _publish(fake, _report(Verdict.APPROVE), options=_options(approve_mode="approve"))
    reviews = writes_of(fake, "submit_review_verdict")
    assert len(reviews) == 1 and reviews[0]["event"] == "APPROVE"


def test_no_formal_approval_by_default() -> None:
    fake = react_provider()
    _publish(fake, _report(Verdict.APPROVE))
    assert writes_of(fake, "submit_review_verdict") == []
    assert _statuses(fake)[0]["state"] == "success"


def test_status_description_is_capped_for_providers() -> None:
    fake = react_provider()
    failed = {f"agent{index}": "x" * 80 for index in range(5)}
    _publish(fake, _report(Verdict.INCOMPLETE, failed=failed))
    assert len(str(_statuses(fake)[0]["description"])) <= 140


def test_status_is_written_against_the_project_and_head() -> None:
    fake = react_provider()
    _publish(fake, _report(Verdict.APPROVE))
    assert _statuses(fake)[0]["project"] == PROJECT


def test_adv23_incomplete_with_a_blocker_is_request_changes_with_a_warning() -> None:
    fake = react_provider()
    report = _report(
        Verdict.REQUEST_CHANGES,
        (_blocker(),),
        failed={"angela": "timed out after 600 s"},
    )
    _publish(fake, report)
    assert [item["state"] for item in _statuses(fake)] == ["failed"]


def test_adv23_incomplete_without_a_blocker_is_pending_and_names_the_agent() -> None:
    fake = react_provider()
    _publish(fake, _report(Verdict.INCOMPLETE, failed={"angela": "HTTP 503"}))
    statuses = _statuses(fake)
    assert [item["state"] for item in statuses] == ["pending"]
    assert "angela" in str(statuses[0]["description"])


def test_adv01_michael_blocker_on_a_non_added_line_still_requests_changes() -> None:
    fake = react_provider()
    stray = make_finding(
        "jim",
        severity="blocker",
        start=500,
        end=500,
        title="Outside the hunk",
        failure="A failure path exists.",
    )
    report = _report(Verdict.REQUEST_CHANGES, (stray,))
    outcome = publish_consolidated(
        fake,
        REF,
        report,
        SUMMARY,
        gate=PostingGate(post_allowed=True),
        options=_options(),
    )
    assert outcome.verdict is Verdict.REQUEST_CHANGES
    assert outcome.posted.discussions == 0


def test_configuration_notes_reach_the_michael_summary() -> None:
    fake = react_provider()
    note = "repo layer ignored: .squad/config.yml: limits.max_iterations is org-only"
    publish_consolidated(
        fake,
        REF,
        _report(Verdict.APPROVE),
        SUMMARY,
        gate=PostingGate(post_allowed=True),
        options=_options(),
        config_notes=[note],
    )
    summary = [
        c for c in fake.list_comments(REF) if summary_marker("michael") in c.body
    ]
    assert "#### Configuration notes" in summary[0].body
    assert note in summary[0].body
