from __future__ import annotations

from typing import Any

import pytest

from code_squad._common.contract import Confidence, Finding, Severity, Verdict
from code_squad._common.findings import (
    PublishOptions,
    PublishOutcome,
    anchor_findings,
    apply_policy,
    compute_verdict,
    dedupe_against_existing,
    dedupe_findings,
    marker,
    publish,
    render_inline_body,
    summary_marker,
)
from code_squad._common.posting import DryRunError, PostingGate
from code_squad._common.safe_retry import MemoryJournal
from code_squad._common.vcs.base import Capability, ChangeRequestRef, Comment
from code_squad._common.vcs.conformance import scenario as s
from code_squad._common.vcs.fake import ALL_CAPABILITIES, FakeVcsProvider

REF: ChangeRequestRef = s.REF
HEAD: str = s.HEAD


def _finding(**overrides: object) -> Finding:
    base: dict[str, object] = {
        "agent": "jim",
        "rule_id": "REACT-001",
        "category": "correctness",
        "severity": Severity.MAJOR,
        "confidence": Confidence.HIGH,
        "file": s.APP_PATH,
        "line_start": 2,
        "line_end": 2,
        "head_sha": HEAD,
        "title": "Greeting is recomputed on every render",
        "rationale": "The import is re-evaluated.",
    }
    base.update(overrides)
    return Finding.model_validate(base).with_id()


_SCENARIO = "An attacker-controlled value reaches the import."


def _seeded() -> FakeVcsProvider:
    fake = FakeVcsProvider()
    s.seed_fake(fake)
    return fake


def _gate(post: bool) -> PostingGate:
    return PostingGate(post_allowed=post)


def _publish(
    fake: FakeVcsProvider,
    findings: list[Finding],
    *,
    post: bool = True,
    options: PublishOptions | None = None,
    journal: MemoryJournal | None = None,
    idempotency_key: str | None = None,
) -> PublishOutcome:
    return publish(
        fake,
        REF,
        HEAD,
        findings,
        "Checked the greeting change.",
        agent="jim",
        gate=_gate(post),
        options=options,
        journal=journal,
        idempotency_key=idempotency_key,
    )


def test_marker_formats_match_the_hidden_comment_contract() -> None:
    assert marker("abc123") == "<!-- code-squad:abc123 -->"
    assert summary_marker("jim") == "<!-- code-squad:summary:jim -->"


def test_anchor_buckets_inline_general_and_dropped() -> None:
    diff = _seeded().get_diff(REF, HEAD)
    inline = _finding(line_start=2, line_end=2)
    outside = _finding(line_start=40, line_end=41, title="Far away change")
    logo = _finding(file=s.LOGO_PATH, line_start=1, line_end=1, title="Logo problem")
    missing = _finding(file="src/other.ts", title="Other file")
    stale = _finding(head_sha="c" * 40, title="Old head")
    report = anchor_findings([inline, outside, logo, missing, stale], diff, HEAD)
    assert [f.id for f, _ in report.inline] == [inline.id]
    general = {f.id: reason for f, reason in report.general}
    assert "outside the changed hunks" in general[outside.id]
    assert "truncated" in general[logo.id]
    dropped = {f.id: reason for f, reason in report.dropped}
    assert "not part of the change request" in dropped[missing.id]
    assert "stale" in dropped[stale.id]


def test_ignore_globs_demote_findings_on_changed_files_to_general_notes() -> None:
    diff = _seeded().get_diff(REF, HEAD)
    report = anchor_findings([_finding()], diff, HEAD, ignore_globs=("src/*.tsx",))
    assert report.inline == ()
    assert report.dropped == ()
    assert report.general[0][1] == "file matches review.ignore_globs"


def test_ignore_globs_still_drop_findings_for_files_outside_the_change() -> None:
    diff = _seeded().get_diff(REF, HEAD)
    outside = _finding(file="src/Missing.tsx")
    report = anchor_findings([outside], diff, HEAD, ignore_globs=("src/*.tsx",))
    assert report.general == ()
    assert "not part of the change request" in report.dropped[0][1]


def test_ignored_file_blocker_still_requests_changes_at_publication() -> None:
    blocker = _finding(severity=Severity.BLOCKER, failure_scenario=_SCENARIO)
    options = PublishOptions(ignore_globs=("src/*.tsx",))
    outcome = _publish(_seeded(), [blocker], options=options)
    assert outcome.verdict is Verdict.REQUEST_CHANGES
    assert [reason for _finding_item, reason in outcome.general] == [
        "file matches review.ignore_globs"
    ]


def _writes(fake: FakeVcsProvider, kind: str) -> list[dict[str, Any]]:
    return [data for name, data in fake.writes if name == kind]


def test_verdict_cap_withholds_approve_as_pending_comment() -> None:
    fake = _seeded()
    options = PublishOptions(
        approve_mode="approve",
        verdict_cap="comment",
        verdict_cap_reason="vulnerability data unavailable/unverified",
    )
    outcome = _publish(fake, [], options=options)
    assert outcome.verdict is Verdict.COMMENT
    status = _writes(fake, "set_status")[-1]
    assert status["state"] == "pending"
    assert (
        status["description"]
        == "approve withheld: vulnerability data unavailable/unverified"
    )
    assert _writes(fake, "submit_review_verdict") == []
    assert outcome.posted.status == "pending"
    assert any(w.startswith("approve withheld") for w in outcome.warnings)


def test_verdict_cap_never_raises_a_blocking_verdict() -> None:
    fake = _seeded()
    options = PublishOptions(verdict_cap="comment", verdict_cap_reason="x")
    blocker = _finding(severity=Severity.BLOCKER, failure_scenario=_SCENARIO)
    outcome = _publish(fake, [blocker], options=options)
    assert outcome.verdict is Verdict.REQUEST_CHANGES
    assert _writes(fake, "set_status")[-1]["state"] == "failed"


def test_uncapped_approve_is_submitted_as_a_formal_approval() -> None:
    fake = _seeded()
    outcome = _publish(fake, [], options=PublishOptions(approve_mode="approve"))
    assert outcome.verdict is Verdict.APPROVE
    assert _writes(fake, "set_status")[-1]["state"] == "success"
    assert [w["event"] for w in _writes(fake, "submit_review_verdict")] == ["APPROVE"]


def test_dedupe_against_existing_skips_findings_with_a_known_marker() -> None:
    known = _finding(title="Already posted")
    fresh = _finding(line_start=3, line_end=3, title="New issue")
    comments = [
        Comment(
            "1",
            "code-squad-bot",
            f"Old body\n{marker(known.id)}",
            s.APP_PATH,
            2,
            None,
            False,
        )
    ]
    new, skipped = dedupe_against_existing([known, fresh], comments)
    assert [f.id for f in new] == [fresh.id]
    assert [f.id for f in skipped] == [known.id]


def test_cross_agent_duplicates_keep_highest_severity_and_list_contributors() -> None:
    jim = _finding(agent="jim", severity=Severity.MINOR, title="Unstable key in list")
    dwight = _finding(
        agent="dwight",
        rule_id="REACT-001",
        severity=Severity.MAJOR,
        confidence=Confidence.HIGH,
        title="Unstable key in list",
        failure_scenario=None,
    )
    unrelated = _finding(agent="jim", line_start=30, line_end=30, title="Other")
    merged = dedupe_findings([jim, dwight, unrelated])
    assert len(merged) == 2
    top = merged[0]
    assert top.finding.severity is Severity.MAJOR
    assert top.finding.agent == "dwight"
    assert top.contributors == ("dwight", "jim")
    assert merged[1].contributors == ("jim",)


def test_overlapping_lines_with_same_rule_merge_even_with_other_titles() -> None:
    first = _finding(agent="jim", title="Alpha")
    second = _finding(agent="angela", title="Beta", line_start=2, line_end=3)
    [merged] = dedupe_findings([first, second])
    assert merged.contributors == ("jim", "angela") or merged.contributors == (
        "angela",
        "jim",
    )


def test_policy_filters_confidence_limits_count_and_marks_summary_only() -> None:
    low = _finding(confidence=Confidence.LOW, title="Maybe", rule_id="R-LOW")
    nit = _finding(severity=Severity.NIT, title="Naming", rule_id="R-NIT")
    major = _finding(title="Real", rule_id="R-MAJ")
    minor = _finding(
        severity=Severity.MINOR,
        title="Small",
        line_start=5,
        line_end=5,
        rule_id="R-MIN",
    )
    policy = apply_policy(
        [low, nit, major, minor],
        min_confidence=Confidence.MEDIUM,
        min_severity_inline=Severity.MINOR,
        max_findings=2,
    )
    kept_ids = [f.id for f in policy.kept]
    assert kept_ids == [major.id, minor.id]
    assert policy.summary_only == frozenset()
    reasons = {f.id: reason for f, reason in policy.dropped}
    assert reasons[low.id] == "below min_confidence"
    assert reasons[nit.id] == "over max_findings"


def test_nits_below_min_severity_are_summary_only() -> None:
    nit = _finding(severity=Severity.NIT, title="Naming")
    policy = apply_policy([nit], min_severity_inline=Severity.MINOR)
    assert policy.summary_only == frozenset({nit.id})


@pytest.mark.parametrize(
    ("severities", "expected"),
    [
        ([Severity.BLOCKER], Verdict.REQUEST_CHANGES),
        ([Severity.MAJOR, Severity.MAJOR, Severity.MAJOR], Verdict.COMMENT),
        ([Severity.MAJOR, Severity.MAJOR], Verdict.APPROVE),
        ([Severity.MINOR, Severity.NIT], Verdict.APPROVE),
        ([], Verdict.APPROVE),
    ],
)
def test_verdict_policy(severities: list[Severity], expected: Verdict) -> None:
    findings = [
        _finding(
            severity=severity,
            title=f"Issue {index}",
            failure_scenario="breaks" if severity is Severity.BLOCKER else None,
            line_start=2 + index,
            line_end=2 + index,
        )
        for index, severity in enumerate(severities)
    ]
    assert compute_verdict(findings, major_threshold=3) is expected


def test_inline_body_contains_suggestion_references_and_marker() -> None:
    finding = _finding(
        suggestion="const greeting = useMemo(() => 'hi', []);",
        references=["https://react.dev"],
    )
    body = render_inline_body(finding)
    assert "```\nconst greeting" in body
    assert "- https://react.dev" in body
    assert marker(finding.id) in body


def test_publish_in_dry_run_raises_and_makes_zero_writes() -> None:
    fake = _seeded()
    with pytest.raises(DryRunError):
        _publish(fake, [_finding()], post=False)
    assert fake.writes == []


def test_publish_posts_inline_comment_summary_and_status() -> None:
    fake = _seeded()
    outcome = _publish(
        fake, [_finding(), _finding(line_start=40, line_end=41, title="Far")]
    )
    kinds = [kind for kind, _ in fake.writes]
    assert kinds.count("post_inline_comments") == 1
    assert "upsert_comment" in kinds
    assert (
        "set_status",
        {
            "project": "acme/web",
            "sha": HEAD,
            "state": "failed",
            "context": "ai-review/jim",
            "description": "blocking findings",
            "backend": "check_run",
        },
    ) not in fake.writes
    assert outcome.posted.discussions == 1
    assert outcome.posted.status == "success"
    # One major finding is enough to block approve under the default threshold of 1.
    assert outcome.verdict is Verdict.COMMENT


def test_publish_is_idempotent_and_does_not_duplicate_comments() -> None:
    fake = _seeded()
    finding = _finding()
    _publish(fake, [finding])
    inline_before = len([c for c in fake.list_comments(REF) if c.path == s.APP_PATH])
    _publish(fake, [finding])
    inline_after = len([c for c in fake.list_comments(REF) if c.path == s.APP_PATH])
    assert inline_after == inline_before
    posts = [data for kind, data in fake.writes if kind == "post_inline_comments"]
    assert len(posts) == 1
    summary_actions = [
        data["action"] for kind, data in fake.writes if kind == "upsert_comment"
    ]
    assert summary_actions == ["update", "update"]
    summaries = [c for c in fake.list_comments(REF) if summary_marker("jim") in c.body]
    assert len(summaries) == 1


def test_journal_prevents_double_post_for_the_same_idempotency_key() -> None:
    fake = _seeded()
    journal = MemoryJournal()
    first = _publish(fake, [_finding()], journal=journal, idempotency_key="run-1")
    writes_after_first = len(fake.writes)
    second = _publish(fake, [_finding()], journal=journal, idempotency_key="run-1")
    assert len(fake.writes) == writes_after_first
    assert first.posted.discussions == 1
    assert second.posted.discussions == 0
    assert any("already completed" in w for w in second.warnings)


def test_status_fallback_warns_on_pat_github() -> None:
    fake = FakeVcsProvider(
        name="github", capabilities=ALL_CAPABILITIES - {Capability.CHECK_RUNS}
    )
    s.seed_fake(fake)
    outcome = _publish(fake, [])
    assert "check runs unavailable; used commit status" in outcome.warnings


def test_approve_mode_none_never_approves() -> None:
    fake = _seeded()
    outcome = _publish(fake, [])
    assert outcome.verdict is Verdict.APPROVE
    assert not [w for w in fake.writes if w[0] == "submit_review_verdict"]


def test_approve_mode_approve_submits_approval_only_for_approve_verdict() -> None:
    fake = _seeded()
    _publish(fake, [], options=PublishOptions(approve_mode="approve"))
    approvals = [data for kind, data in fake.writes if kind == "submit_review_verdict"]
    assert [a["event"] for a in approvals] == ["APPROVE"]
    blocking = _finding(
        severity=Severity.BLOCKER, failure_scenario="crash", title="Crash"
    )
    _publish(fake, [blocking], options=PublishOptions(approve_mode="approve"))
    approvals = [data for kind, data in fake.writes if kind == "submit_review_verdict"]
    assert len(approvals) == 1


def test_stale_head_drops_findings_and_sets_pending_status() -> None:
    fake = _seeded()
    fake.set_head(REF, "c" * 40)
    outcome = _publish(fake, [_finding()])
    assert not [w for w in fake.writes if w[0] == "post_inline_comments"]
    assert outcome.posted.status == "pending"
    assert any("head moved" in w for w in outcome.warnings)


def test_general_notes_and_warnings_land_in_the_summary_body() -> None:
    fake = _seeded()
    _publish(
        fake, [_finding(file=s.LOGO_PATH, line_start=1, line_end=1, title="Logo issue")]
    )
    summary = [c for c in fake.list_comments(REF) if summary_marker("jim") in c.body]
    assert summary
    assert "Logo issue" in summary[0].body
    assert "General notes" in summary[0].body


def test_comment_style_inline_skips_the_summary() -> None:
    fake = _seeded()
    _publish(fake, [_finding()], options=PublishOptions(comment_style="inline"))
    assert not [w for w in fake.writes if w[0] == "upsert_comment"]


def test_comment_style_summary_demotes_inline_findings_to_the_summary() -> None:
    fake = _seeded()
    outcome = _publish(
        fake, [_finding()], options=PublishOptions(comment_style="summary")
    )
    assert not [w for w in fake.writes if w[0] == "post_inline_comments"]
    assert outcome.general[0][1] == "inline comments disabled for this run"
