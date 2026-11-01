"""The single publication path of the orchestrator.

``findings.publish`` derives the verdict and the commit status from the findings alone,
so it cannot publish an ``incomplete`` consolidated result. This module reuses the same
building blocks (anchoring, policy, marker dedupe, rendering) and takes the verdict from
the consolidated report. An incomplete report is published as ``pending``, never as
``success``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from code_squad._common.contract import Finding, Posted, Verdict
from code_squad._common.findings import (
    PublishOptions,
    anchor_findings,
    apply_policy,
    dedupe_against_existing,
    render_inline_body,
    summary_marker,
)
from code_squad._common.posting import DryRunError, PostingGate
from code_squad._common.vcs.base import (
    Capability,
    CapabilityError,
    ChangeRequestRef,
    FileDiff,
    InlineComment,
    StaleHeadError,
    StatusState,
    VcsProvider,
)
from code_squad.michael.aggregate import ConsolidatedReport

DEFAULT_CONTEXT: Final = "ai-review/michael"
STALE_WARNING: Final = "change request head moved during review; nothing was published"
_STATUS: Final[dict[Verdict, StatusState]] = {
    Verdict.APPROVE: StatusState.SUCCESS,
    Verdict.COMMENT: StatusState.SUCCESS,
    Verdict.REQUEST_CHANGES: StatusState.FAILED,
    Verdict.INCOMPLETE: StatusState.PENDING,
}
_DESCRIPTION: Final[dict[Verdict, str]] = {
    Verdict.APPROVE: "no blocking findings",
    Verdict.COMMENT: "review comments posted",
    Verdict.REQUEST_CHANGES: "blocking findings",
    Verdict.INCOMPLETE: "review incomplete",
}
_MAX_DESCRIPTION: Final = 140


@dataclass(frozen=True)
class Publication:
    posted: Posted
    warnings: tuple[str, ...]


def publish_consolidated(
    provider: VcsProvider,
    ref: ChangeRequestRef,
    report: ConsolidatedReport,
    summary: str,
    *,
    gate: PostingGate,
    options: PublishOptions,
) -> Publication:
    warnings = _capability_warnings(provider)
    try:
        gate.require_write("publish_review")
    except DryRunError:
        return Publication(Posted(), tuple(warnings))
    head = report.head_sha
    context = options.status_context or DEFAULT_CONTEXT
    diff = _diff_at_head(provider, ref, head)
    if diff is None:
        provider.set_status(
            ref.project, head, StatusState.PENDING, context, "stale head", ""
        )
        return Publication(Posted(status="pending"), (*warnings, STALE_WARNING))
    policy = apply_policy(
        list(report.findings),
        min_confidence=options.min_confidence,
        min_severity_inline=options.min_severity_inline,
        max_findings=options.max_findings,
    )
    anchored = anchor_findings(
        policy.kept, diff, head, ignore_globs=options.ignore_globs
    )
    inline = _inline_candidates(anchored.inline, policy.summary_only, options)
    new_inline, _skipped = dedupe_against_existing(inline, provider.list_comments(ref))
    posted = Posted()
    if new_inline:
        comments = [
            InlineComment(
                item.file,
                item.line_start,
                _inline_body(item, report.contributors.get(item.id, (item.agent,))),
            )
            for item in new_inline
        ]
        provider.post_inline_comments(ref, head, comments, provider.get_diff_refs(ref))
        posted = posted.model_copy(update={"discussions": len(comments)})
    if options.comment_style in ("summary", "both"):
        provider.upsert_comment(ref, summary_marker("michael"), summary)
        posted = posted.model_copy(update={"notes": 1})
    state = _STATUS[report.verdict]
    provider.set_status(ref.project, head, state, context, _description(report), "")
    posted = posted.model_copy(update={"status": state.value})
    warnings.extend(_approve(provider, ref, head, report.verdict, options))
    return Publication(posted, tuple(warnings))


def _diff_at_head(
    provider: VcsProvider, ref: ChangeRequestRef, head: str
) -> tuple[FileDiff, ...] | None:
    try:
        current = provider.get_change_request(ref).head_sha
        if current != head:
            return None
        return provider.get_diff(ref, head)
    except StaleHeadError:
        return None


def _inline_candidates(
    anchored: Sequence[tuple[Finding, str]],
    summary_only: frozenset[str],
    options: PublishOptions,
) -> list[Finding]:
    if options.comment_style == "summary":
        return []
    return [item for item, _reason in anchored if item.id not in summary_only]


def _inline_body(finding: Finding, contributors: Sequence[str]) -> str:
    return f"Reported by: {', '.join(contributors)}\n\n{render_inline_body(finding)}"


def _description(report: ConsolidatedReport) -> str:
    if report.verdict is Verdict.INCOMPLETE:
        text = "review incomplete: " + ", ".join(sorted(report.failed))
    else:
        text = _DESCRIPTION[report.verdict]
    return text[:_MAX_DESCRIPTION]


def _capability_warnings(provider: VcsProvider) -> list[str]:
    if provider.name == "github" and Capability.CHECK_RUNS not in provider.capabilities:
        return ["check runs unavailable; used commit status"]
    return []


def _approve(
    provider: VcsProvider,
    ref: ChangeRequestRef,
    head: str,
    verdict: Verdict,
    options: PublishOptions,
) -> list[str]:
    if verdict is not Verdict.APPROVE or options.approve_mode == "none":
        return []
    event: Literal["APPROVE", "COMMENT"] = (
        "APPROVE" if options.approve_mode == "approve" else "COMMENT"
    )
    try:
        provider.submit_review_verdict(
            ref, head, event, "Automated review: no blocking findings."
        )
    except CapabilityError:
        return ["formal review is not supported by this provider"]
    return []
