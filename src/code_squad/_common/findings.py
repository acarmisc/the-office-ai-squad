"""Deterministic finding pipeline: anchoring, dedupe, policy, verdict, publication."""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal

from code_squad._common.contract import (
    Confidence,
    Finding,
    Posted,
    Severity,
    Verdict,
    severity_rank,
)
from code_squad._common.posting import PostingGate
from code_squad._common.safe_retry import OperationJournal, run_once
from code_squad._common.vcs.base import (
    ApproveMode,
    Capability,
    CapabilityError,
    ChangeRequestRef,
    Comment,
    FileDiff,
    InlineComment,
    StaleHeadError,
    StatusState,
    VcsProvider,
)
from code_squad._common.vcs.diff import line_in_changed_hunk

CommentStyle = Literal["inline", "summary", "both"]
Bucket = Literal["inline", "general", "dropped"]
_MARKER_RE: Final = re.compile(r"<!-- code-squad:([^\s>]+) -->")
_WORD_RE: Final = re.compile(r"[a-z]{4,}")
_STOPWORDS: Final = frozenset(
    {
        "this",
        "that",
        "with",
        "from",
        "when",
        "into",
        "could",
        "should",
        "might",
        "which",
        "there",
    }
)
_CONFIDENCE_RANK: Final[dict[Confidence, int]] = {
    Confidence.LOW: 0,
    Confidence.MEDIUM: 1,
    Confidence.HIGH: 2,
}
_STATUS: Final[dict[Verdict, tuple[StatusState, str]]] = {
    Verdict.APPROVE: (StatusState.SUCCESS, "no blocking findings"),
    Verdict.COMMENT: (StatusState.SUCCESS, "review comments posted"),
    Verdict.REQUEST_CHANGES: (StatusState.FAILED, "blocking findings"),
    Verdict.INCOMPLETE: (StatusState.PENDING, "review incomplete"),
}
_STALE_WARNING: Final = "change request head moved during review; findings were dropped"


def marker(finding_id: str) -> str:
    return f"<!-- code-squad:{finding_id} -->"


def summary_marker(agent: str) -> str:
    return f"<!-- code-squad:summary:{agent} -->"


@dataclass(frozen=True)
class AnchorReport:
    inline: tuple[tuple[Finding, str], ...] = ()
    general: tuple[tuple[Finding, str], ...] = ()
    dropped: tuple[tuple[Finding, str], ...] = ()


@dataclass(frozen=True)
class MergedFinding:
    finding: Finding
    contributors: tuple[str, ...]


@dataclass(frozen=True)
class PolicyResult:
    kept: tuple[Finding, ...]
    summary_only: frozenset[str]
    dropped: tuple[tuple[Finding, str], ...]


@dataclass(frozen=True)
class PublishOptions:
    comment_style: CommentStyle = "both"
    approve_mode: ApproveMode = "none"
    status_context: str | None = None
    ignore_globs: tuple[str, ...] = ()
    min_confidence: Confidence = Confidence.MEDIUM
    min_severity_inline: Severity = Severity.MINOR
    max_findings: int = 50
    major_threshold: int = 1


@dataclass(frozen=True)
class PublishOutcome:
    posted: Posted
    warnings: tuple[str, ...]
    verdict: Verdict
    inline: tuple[Finding, ...] = field(default=())
    general: tuple[tuple[Finding, str], ...] = field(default=())


def anchor_findings(
    findings: Sequence[Finding],
    diff: Sequence[FileDiff],
    current_head: str,
    *,
    ignore_globs: Sequence[str] = (),
) -> AnchorReport:
    files = {file_diff.path: file_diff for file_diff in diff}
    buckets: dict[Bucket, list[tuple[Finding, str]]] = {
        "inline": [],
        "general": [],
        "dropped": [],
    }
    for finding in findings:
        bucket, reason = _anchor_one(finding, files, current_head, ignore_globs)
        buckets[bucket].append((finding, reason))
    return AnchorReport(
        inline=tuple(buckets["inline"]),
        general=tuple(buckets["general"]),
        dropped=tuple(buckets["dropped"]),
    )


def _anchor_one(
    finding: Finding,
    files: dict[str, FileDiff],
    head: str,
    ignore_globs: Sequence[str],
) -> tuple[Bucket, str]:
    if finding.head_sha != head:
        return "dropped", "stale: finding was produced for another head"
    if any(fnmatch.fnmatch(finding.file, glob) for glob in ignore_globs):
        return "dropped", "path matches review ignore_globs"
    file_diff = files.get(finding.file)
    if file_diff is None:
        return "dropped", "file is not part of the change request"
    if file_diff.truncated:
        return "general", "file diff is truncated; posted as a general note"
    if not line_in_changed_hunk(file_diff, finding.line_start, finding.line_end):
        return "general", "lines are outside the changed hunks"
    return "inline", "anchored to changed lines"


def dedupe_against_existing(
    findings: Sequence[Finding], comments: Sequence[Comment]
) -> tuple[list[Finding], list[Finding]]:
    known = _known_markers(comments)
    new = [finding for finding in findings if finding.id not in known]
    skipped = [finding for finding in findings if finding.id in known]
    return new, skipped


def _known_markers(comments: Iterable[Comment]) -> set[str]:
    known: set[str] = set()
    for comment in comments:
        known.update(_MARKER_RE.findall(comment.body))
    return known


def dedupe_findings(findings: Sequence[Finding]) -> list[MergedFinding]:
    ordered = sorted(findings, key=lambda item: -severity_rank(item.severity))
    clusters: list[list[Finding]] = []
    for finding in ordered:
        for cluster in clusters:
            if _overlaps(cluster[0], finding):
                cluster.append(finding)
                break
        else:
            clusters.append([finding])
    return [
        MergedFinding(cluster[0], tuple(dict.fromkeys(item.agent for item in cluster)))
        for cluster in clusters
    ]


def _overlaps(first: Finding, second: Finding) -> bool:
    if first.file != second.file:
        return False
    if first.line_start > second.line_end or second.line_start > first.line_end:
        return False
    if first.rule_id == second.rule_id:
        return True
    return first.category == second.category and bool(
        _words(first.title) & _words(second.title)
    )


def _words(title: str) -> set[str]:
    return {word for word in _WORD_RE.findall(title.lower()) if word not in _STOPWORDS}


def apply_policy(
    findings: Sequence[Finding],
    *,
    min_confidence: Confidence = Confidence.MEDIUM,
    min_severity_inline: Severity = Severity.MINOR,
    max_findings: int = 50,
) -> PolicyResult:
    kept: list[Finding] = []
    dropped: list[tuple[Finding, str]] = []
    for finding in findings:
        if _CONFIDENCE_RANK[finding.confidence] < _CONFIDENCE_RANK[min_confidence]:
            dropped.append((finding, "below min_confidence"))
        else:
            kept.append(finding)
    ordered = sorted(kept, key=_priority, reverse=True)
    dropped.extend((finding, "over max_findings") for finding in ordered[max_findings:])
    final = ordered[:max_findings]
    summary_only = frozenset(
        finding.id
        for finding in final
        if severity_rank(finding.severity) < severity_rank(min_severity_inline)
    )
    return PolicyResult(tuple(final), summary_only, tuple(dropped))


def _priority(finding: Finding) -> tuple[int, int]:
    return severity_rank(finding.severity), _CONFIDENCE_RANK[finding.confidence]


def compute_verdict(findings: Sequence[Finding], major_threshold: int = 1) -> Verdict:
    if any(item.severity is Severity.BLOCKER for item in findings):
        return Verdict.REQUEST_CHANGES
    majors = sum(1 for item in findings if item.severity is Severity.MAJOR)
    if majors >= major_threshold:
        return Verdict.COMMENT
    return Verdict.APPROVE


def render_inline_body(finding: Finding) -> str:
    lines = [
        f"**{finding.title}**",
        "",
        f"Severity: `{finding.severity.value}` · "
        f"Confidence: `{finding.confidence.value}` · Rule: `{finding.rule_id}`",
        "",
        finding.rationale,
    ]
    if finding.failure_scenario:
        lines += ["", f"Failure scenario: {finding.failure_scenario}"]
    if finding.suggestion:
        lines += ["", _fenced(finding.suggestion.rstrip("\n"))]
    if finding.references:
        lines += ["", "References:", *[f"- {ref}" for ref in finding.references]]
    lines += ["", marker(finding.id)]
    return "\n".join(lines)


def _fenced(code: str) -> str:
    fence = "````" if "```" in code else "```"
    return f"{fence}\n{code}\n{fence}"


def render_summary(
    agent: str,
    verdict: Verdict,
    summary: str,
    inline: Sequence[Finding],
    general: Sequence[tuple[Finding, str]],
    warnings: Sequence[str],
    head_sha: str,
) -> str:
    lines = [
        f"### Review by `{agent}`",
        "",
        f"Verdict: **{verdict.value}** at head `{head_sha[:12]}`",
        "",
        summary,
        "",
        f"Inline comments: {len(inline)}. General notes: {len(general)}.",
    ]
    if general:
        lines += ["", "#### General notes"]
        lines += [
            f"- `{finding.severity.value}` {finding.title} "
            f"({finding.file}:{finding.line_start}): {reason}"
            for finding, reason in general
        ]
    if warnings:
        lines += ["", "#### Warnings", *[f"- {warning}" for warning in warnings]]
    lines += ["", summary_marker(agent)]
    return "\n".join(lines)


def publish(
    provider: VcsProvider,
    ref: ChangeRequestRef,
    head_sha: str,
    findings: Sequence[Finding],
    summary: str,
    *,
    agent: str,
    gate: PostingGate,
    options: PublishOptions | None = None,
    journal: OperationJournal | None = None,
    idempotency_key: str | None = None,
) -> PublishOutcome:
    gate.require_write("publish_review")
    opts = options or PublishOptions()
    unique = _unique_by_id(findings)
    if journal is None:
        return _publish_once(provider, ref, head_sha, unique, summary, agent, opts)
    key = idempotency_key or f"{agent}:{ref.project}#{ref.number}@{head_sha}"
    value, executed = run_once(
        journal,
        key,
        "publish_review",
        lambda: _encode(
            _publish_once(provider, ref, head_sha, unique, summary, agent, opts)
        ),
    )
    outcome = _decode(value)
    if executed:
        return outcome
    return replace(
        outcome,
        posted=Posted(),
        warnings=(
            *outcome.warnings,
            "publish skipped: already completed for this idempotency key",
        ),
    )


def _publish_once(
    provider: VcsProvider,
    ref: ChangeRequestRef,
    head_sha: str,
    findings: Sequence[Finding],
    summary: str,
    agent: str,
    opts: PublishOptions,
) -> PublishOutcome:
    context = opts.status_context or f"ai-review/{agent}"
    warnings = _status_warnings(provider)
    if _head_moved(provider, ref, head_sha):
        return _stale(provider, ref, head_sha, context, warnings)
    policy = apply_policy(
        [item.with_id() for item in findings],
        min_confidence=opts.min_confidence,
        min_severity_inline=opts.min_severity_inline,
        max_findings=opts.max_findings,
    )
    report = anchor_findings(
        policy.kept,
        provider.get_diff(ref, head_sha),
        head_sha,
        ignore_globs=opts.ignore_globs,
    )
    inline, general = _placement(report, policy.summary_only, opts.comment_style)
    new_inline, _skipped = dedupe_against_existing(inline, provider.list_comments(ref))
    posted = Posted()
    if new_inline:
        comments = [
            InlineComment(item.file, item.line_start, render_inline_body(item))
            for item in new_inline
        ]
        provider.post_inline_comments(
            ref, head_sha, comments, provider.get_diff_refs(ref)
        )
        posted = posted.model_copy(update={"discussions": len(new_inline)})
    valid = [*inline, *(item for item, _ in general)]
    verdict = compute_verdict(valid, opts.major_threshold)
    if opts.comment_style in ("summary", "both"):
        body = render_summary(
            agent, verdict, summary, inline, general, warnings, head_sha
        )
        provider.upsert_comment(ref, summary_marker(agent), body)
        posted = posted.model_copy(update={"notes": 1})
    state, description = _STATUS[verdict]
    provider.set_status(ref.project, head_sha, state, context, description, "")
    posted = posted.model_copy(update={"status": state.value})
    warnings.extend(_approve(provider, ref, head_sha, verdict, opts))
    return PublishOutcome(
        posted, tuple(warnings), verdict, tuple(inline), tuple(general)
    )


def _unique_by_id(findings: Sequence[Finding]) -> list[Finding]:
    unique: dict[str, Finding] = {}
    for item in findings:
        stamped = item.with_id()
        unique.setdefault(stamped.id, stamped)
    return list(unique.values())


def _placement(
    report: AnchorReport,
    summary_only: frozenset[str],
    style: CommentStyle,
) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    inline: list[Finding] = []
    general: list[tuple[Finding, str]] = list(report.general)
    for finding, _reason in report.inline:
        if style == "summary":
            general.append((finding, "inline comments disabled for this run"))
        elif finding.id in summary_only:
            general.append((finding, "below min_severity_inline; summary only"))
        else:
            inline.append(finding)
    return inline, general


def _head_moved(provider: VcsProvider, ref: ChangeRequestRef, head_sha: str) -> bool:
    try:
        return provider.get_change_request(ref).head_sha != head_sha
    except StaleHeadError:
        return True


def _stale(
    provider: VcsProvider,
    ref: ChangeRequestRef,
    head_sha: str,
    context: str,
    warnings: list[str],
) -> PublishOutcome:
    provider.set_status(
        ref.project, head_sha, StatusState.PENDING, context, "stale head", ""
    )
    warnings.append(_STALE_WARNING)
    return PublishOutcome(Posted(status="pending"), tuple(warnings), Verdict.INCOMPLETE)


def _status_warnings(provider: VcsProvider) -> list[str]:
    if provider.name == "github" and Capability.CHECK_RUNS not in provider.capabilities:
        return ["check runs unavailable; used commit status"]
    return []


def _approve(
    provider: VcsProvider,
    ref: ChangeRequestRef,
    head_sha: str,
    verdict: Verdict,
    opts: PublishOptions,
) -> list[str]:
    if verdict is not Verdict.APPROVE or opts.approve_mode == "none":
        return []
    event: Literal["APPROVE", "COMMENT"] = (
        "APPROVE" if opts.approve_mode == "approve" else "COMMENT"
    )
    try:
        provider.submit_review_verdict(
            ref, head_sha, event, "Automated review: no blocking findings."
        )
    except CapabilityError:
        return ["formal review is not supported by this provider"]
    return []


def _encode(outcome: PublishOutcome) -> str:
    payload: dict[str, Any] = {
        "posted": outcome.posted.model_dump(),
        "warnings": list(outcome.warnings),
        "verdict": outcome.verdict.value,
    }
    return json.dumps(payload, sort_keys=True)


def _decode(value: str) -> PublishOutcome:
    data = json.loads(value)
    return PublishOutcome(
        posted=Posted.model_validate(data["posted"]),
        warnings=tuple(str(item) for item in data["warnings"]),
        verdict=Verdict(data["verdict"]),
    )
