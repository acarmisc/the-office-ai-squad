"""Deterministic finding pipeline: normalise, anchor, dedupe, verdict, publish.

Every agent, michael included, publishes through ``publish``. The verdict is
computed over every schema-valid finding after dedupe. Anchoring only decides where a
finding is shown: a finding that cannot be anchored inline becomes a general note, and
only a finding on a file outside the change is dropped, which still keeps the verdict
from approving.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from urllib.parse import urlsplit

from code_squad._common.config.globs import glob_match
from code_squad._common.contract import (
    Confidence,
    Finding,
    Posted,
    Severity,
    Verdict,
    severity_rank,
)
from code_squad._common.posting import PostingGate
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
    same_login,
)
from code_squad._common.vcs.diff import added_range

CommentStyle = Literal["inline", "summary", "both"]
VerdictCap = Literal["approve", "comment", "request_changes"]
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
_STALE_WARNING: Final = "change request head moved during review; nothing was published"
_IGNORED_NOTE: Final = "file matches review.ignore_globs"
_TRUNCATED_NOTE: Final = "file diff is truncated; posted as a general note"
_BINARY_NOTE: Final = "file is binary; posted as a general note"
_NOT_ADDED_NOTE: Final = "lines are not added lines; posted as a general note"
_REJECTED_NOTE: Final = "the VCS rejected the inline comment; posted as a general note"
_SUMMARY_ONLY_CONFIDENCE: Final = "below min_confidence; summary only"
_SUMMARY_ONLY_SEVERITY: Final = "below min_severity_inline; summary only"
_SUMMARY_ONLY_LIMIT: Final = "over max_findings; summary only"
_INLINE_DISABLED: Final = "inline comments disabled for this run"
_MAX_DESCRIPTION: Final = 140
_MAX_WARNING: Final = 300
_ORDER: Final[dict[Verdict, int]] = {
    Verdict.APPROVE: 0,
    Verdict.COMMENT: 1,
    Verdict.REQUEST_CHANGES: 2,
}
_VERDICT_RANK: Final[dict[Verdict, int]] = {
    Verdict.INCOMPLETE: -1,
    Verdict.REQUEST_CHANGES: 0,
    Verdict.COMMENT: 1,
    Verdict.APPROVE: 2,
}
_ALLOWED_LINK_HOSTS: Final = frozenset(
    {"cwe.mitre.org", "owasp.org", "nvd.nist.gov", "osv.dev"}
)
_ADVISORY_PREFIX: Final = "/advisories/"
_IMAGE: Final = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_RAW_IMAGE: Final = re.compile(r"<img\b[^>]*>?", re.IGNORECASE)
_LINK_OR_URL: Final = re.compile(
    r"\[(?P<text>[^\]]*)\]\((?P<link>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"|(?P<url>https?://[^\s<>()\[\]`]+)"
)
_TAG_OPEN: Final = re.compile(r"<(?=[A-Za-z/!])")
_MENTION: Final = re.compile(r"@(?=[A-Za-z0-9_.\-\[])")
_LINE_START_SLASH: Final = re.compile(r"^/", re.MULTILINE)
_ZERO_WIDTH: Final = "​"


def marker(finding_id: str) -> str:
    return f"<!-- code-squad:{finding_id} -->"


def summary_marker(agent: str) -> str:
    return f"<!-- code-squad:summary:{agent} -->"


def summary_notes_of(services: Mapping[str, Any]) -> list[str]:
    """Configuration notes carried in ``services["summary_notes"]``, as text."""
    notes = services.get("summary_notes")
    return [str(item) for item in notes] if isinstance(notes, list) else []


def normalise_path(path: str) -> str:
    """Repository-relative form: no leading ``./`` or ``/``, no doubled slashes."""
    cleaned = path.strip()
    previous = None
    while cleaned != previous:
        previous = cleaned
        cleaned = cleaned.lstrip("/").removeprefix("./").replace("//", "/")
    return cleaned


def neutralise_markdown(text: str, *, vcs_host: str | None = None) -> str:
    """Make model-authored markdown inert: no quick actions, mentions, images or tags.

    Line-leading ``/`` is escaped so GitLab does not run it as a quick action, ``@``
    gets a zero-width space so it is not a mention, and links outside the allow-list are
    shown as code rather than as links.
    """
    out = _IMAGE.sub("[image removed]", text)
    out = _RAW_IMAGE.sub("[image removed]", out)
    out = _TAG_OPEN.sub("&lt;", out)
    out = _LINK_OR_URL.sub(lambda match: _link(match, vcs_host), out)
    out = _MENTION.sub("@" + _ZERO_WIDTH, out)
    return _LINE_START_SLASH.sub(r"\\/", out)


def _link(match: re.Match[str], vcs_host: str | None) -> str:
    if match.group("url") is not None:
        url = match.group("url")
        return url if _allowed_link(url, vcs_host) else f"`{url}`"
    text, link = match.group("text"), match.group("link")
    if _allowed_link(link, vcs_host):
        return match.group(0)
    return f"{text} (`{link}`)" if text.strip() else f"`{link}`"


def _allowed_link(url: str, vcs_host: str | None) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    host = (parts.hostname or "").lower()
    if host in _ALLOWED_LINK_HOSTS or host.endswith(".owasp.org"):
        return True
    if host == "github.com":
        return parts.path.startswith(_ADVISORY_PREFIX)
    if vcs_host is not None and host == vcs_host.lower():
        return parts.path.startswith(("/help", "/docs"))
    return False


def _code(text: str) -> str:
    return " ".join(text.replace("`", "'").split())


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
    """Every finding is kept for the verdict; ``summary_only`` only limits placement."""

    kept: tuple[Finding, ...]
    summary_only: frozenset[str]
    reasons: Mapping[str, str] = field(default_factory=dict)


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
    verdict_cap: VerdictCap | None = None
    verdict_cap_reason: str | None = None


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
    inline: list[tuple[Finding, str]] = []
    general: list[tuple[Finding, str]] = []
    dropped: list[tuple[Finding, str]] = []
    for finding in findings:
        bucket, reason = _anchor_one(finding, files, current_head, ignore_globs)
        target = {"inline": inline, "general": general, "dropped": dropped}[bucket]
        target.append((finding, reason))
    return AnchorReport(tuple(inline), tuple(general), tuple(dropped))


def _anchor_one(
    finding: Finding,
    files: dict[str, FileDiff],
    head: str,
    ignore_globs: Sequence[str],
) -> tuple[Literal["inline", "general", "dropped"], str]:
    if finding.head_sha != head:
        return "dropped", "stale: finding was produced for another head"
    file_diff = files.get(finding.file)
    if file_diff is None:
        return "dropped", "file is not part of the change request"
    if any(glob_match(glob, finding.file) for glob in ignore_globs):
        return "general", _IGNORED_NOTE
    if file_diff.binary:
        return "general", _BINARY_NOTE
    if file_diff.truncated:
        return "general", _TRUNCATED_NOTE
    if not added_range(file_diff, finding.line_start, finding.line_end):
        return "general", _NOT_ADDED_NOTE
    return "inline", "anchored to added lines"


def dedupe_against_existing(
    findings: Sequence[Finding], comments: Sequence[Comment], *, bot: str
) -> tuple[list[Finding], list[Finding]]:
    known = _known_markers(comments, bot)
    new = [finding for finding in findings if finding.id not in known]
    skipped = [finding for finding in findings if finding.id in known]
    return new, skipped


def _known_markers(comments: Iterable[Comment], bot: str) -> set[str]:
    known: set[str] = set()
    for comment in comments:
        if same_login(comment.author, bot):
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
    reasons: dict[str, str] = {}
    summary_only: set[str] = set()
    for finding in findings:
        if _CONFIDENCE_RANK[finding.confidence] < _CONFIDENCE_RANK[min_confidence]:
            summary_only.add(finding.id)
            reasons[finding.id] = _SUMMARY_ONLY_CONFIDENCE
        elif severity_rank(finding.severity) < severity_rank(min_severity_inline):
            summary_only.add(finding.id)
            reasons[finding.id] = _SUMMARY_ONLY_SEVERITY
    inline_candidates = sorted(
        (item for item in findings if item.id not in summary_only),
        key=_priority,
        reverse=True,
    )
    for finding in inline_candidates[max_findings:]:
        summary_only.add(finding.id)
        reasons[finding.id] = _SUMMARY_ONLY_LIMIT
    return PolicyResult(tuple(findings), frozenset(summary_only), reasons)


def _priority(finding: Finding) -> tuple[int, int]:
    return severity_rank(finding.severity), _CONFIDENCE_RANK[finding.confidence]


def compute_verdict(findings: Sequence[Finding], major_threshold: int = 1) -> Verdict:
    if any(item.severity is Severity.BLOCKER for item in findings):
        return Verdict.REQUEST_CHANGES
    majors = sum(1 for item in findings if item.severity is Severity.MAJOR)
    if majors >= major_threshold:
        return Verdict.COMMENT
    return Verdict.APPROVE


def resolve_verdict(
    findings: Sequence[Finding],
    *,
    incomplete: Sequence[str] = (),
    major_threshold: int = 1,
    floor: Verdict = Verdict.APPROVE,
) -> Verdict:
    """Incomplete review: request changes when a blocker exists, else incomplete."""
    if incomplete:
        blocked = any(item.severity is Severity.BLOCKER for item in findings)
        return Verdict.REQUEST_CHANGES if blocked else Verdict.INCOMPLETE
    return _lift(compute_verdict(findings, major_threshold), floor)


def _lift(verdict: Verdict, floor: Verdict) -> Verdict:
    if verdict is Verdict.INCOMPLETE or floor is Verdict.INCOMPLETE:
        return verdict
    return max(verdict, floor, key=_ORDER.__getitem__)


def render_inline_body(
    finding: Finding,
    contributors: Sequence[str] | None = None,
    *,
    vcs_host: str | None = None,
) -> str:
    lines: list[str] = []
    if contributors:
        lines += [f"Reported by: {', '.join(contributors)}", ""]
    lines += [
        f"**{neutralise_markdown(finding.title, vcs_host=vcs_host)}**",
        "",
        f"Severity: `{finding.severity.value}` · "
        f"Confidence: `{finding.confidence.value}` · Rule: `{_code(finding.rule_id)}`",
        "",
        neutralise_markdown(finding.rationale, vcs_host=vcs_host),
    ]
    if finding.failure_scenario:
        scenario = neutralise_markdown(finding.failure_scenario, vcs_host=vcs_host)
        lines += ["", f"Failure scenario: {scenario}"]
    if finding.suggestion:
        lines += ["", _fenced(finding.suggestion.rstrip("\n"))]
    if finding.references:
        lines += [
            "",
            "References:",
            *[
                f"- {neutralise_markdown(ref, vcs_host=vcs_host)}"
                for ref in finding.references
            ],
        ]
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
    *,
    incomplete: Mapping[str, str] | None = None,
    not_reviewed: Sequence[str] = (),
    config_notes: Sequence[str] = (),
    vcs_host: str | None = None,
) -> str:
    lines = [
        f"### Review by `{agent}`",
        "",
        _verdict_line(verdict, head_sha, incomplete or {}),
        "",
        neutralise_markdown(summary, vcs_host=vcs_host),
        "",
        f"Inline comments: {len(inline)}. General notes: {len(general)}.",
    ]
    if general:
        lines += ["", "#### General notes"]
        lines += [
            f"- `{finding.severity.value}` "
            f"{neutralise_markdown(finding.title, vcs_host=vcs_host)} "
            f"({_code(finding.file)}:{finding.line_start}): {reason}"
            for finding, reason in general
        ]
    if not_reviewed:
        lines += [
            "",
            "#### Not reviewed",
            "",
            "These files were truncated or binary and are not covered by this verdict.",
            *[f"- `{_code(path)}`" for path in not_reviewed],
        ]
    if config_notes:
        lines += [
            "",
            "#### Configuration notes",
            *[
                f"- {neutralise_markdown(item, vcs_host=vcs_host)}"
                for item in config_notes
            ],
        ]
    if warnings:
        lines += ["", "#### Warnings", *[f"- {item}" for item in warnings]]
    lines += ["", summary_marker(agent)]
    return "\n".join(lines)


def _verdict_line(
    verdict: Verdict, head_sha: str, incomplete: Mapping[str, str]
) -> str:
    head = head_sha[:12]
    if verdict is not Verdict.INCOMPLETE:
        return f"Verdict: **{verdict.value}** at head `{head}`."
    names = ", ".join(
        f"`{_code(agent)}` ({_code(reason)[:120]})"
        for agent, reason in incomplete.items()
    )
    return (
        f"Verdict: **incomplete** at head `{head}`. The verdict is not final because "
        f"these specialists did not complete: {names or 'none reported'}. Re-run the "
        "review for a final verdict."
    )


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
    contributors: Mapping[str, tuple[str, ...]] | None = None,
    incomplete: Mapping[str, str] | None = None,
    verdict_floor: Verdict = Verdict.APPROVE,
    extra_warnings: Sequence[str] = (),
    config_notes: Sequence[str] = (),
) -> PublishOutcome:
    gate.require_write("publish_review")
    return _publish_once(
        provider,
        ref,
        head_sha,
        findings,
        summary,
        agent=agent,
        opts=options or PublishOptions(),
        contributors=contributors or {},
        incomplete=dict(incomplete or {}),
        floor=verdict_floor,
        extra=tuple(extra_warnings),
        notes=tuple(config_notes),
    )


def _publish_once(
    provider: VcsProvider,
    ref: ChangeRequestRef,
    head_sha: str,
    findings: Sequence[Finding],
    summary: str,
    *,
    agent: str,
    opts: PublishOptions,
    contributors: Mapping[str, tuple[str, ...]],
    incomplete: dict[str, str],
    floor: Verdict,
    extra: tuple[str, ...],
    notes: tuple[str, ...],
) -> PublishOutcome:
    context = opts.status_context or f"ai-review/{agent}"
    warnings = [*_status_warnings(provider), *extra]
    if _head_moved(provider, ref, head_sha):
        return _stale(provider, ref, head_sha, context, warnings)
    stamped = _stamp_all(findings, head_sha)
    policy = apply_policy(
        stamped,
        min_confidence=opts.min_confidence,
        min_severity_inline=opts.min_severity_inline,
        max_findings=opts.max_findings,
    )
    diff = provider.get_diff(ref, head_sha)
    host = urlsplit(provider.clone_url(ref.project)).netloc or None
    report = anchor_findings(
        policy.kept, diff, head_sha, ignore_globs=opts.ignore_globs
    )
    considered = [item for item, _ in (*report.inline, *report.general)]
    dropped_major = [
        item
        for item, _ in report.dropped
        if item.severity in (Severity.BLOCKER, Severity.MAJOR)
    ]
    warnings.extend(_dropped_warnings(report.dropped, host))
    not_reviewed = tuple(item.path for item in diff if item.truncated or item.binary)
    capping = tuple(item.path for item in diff if item.truncated and not item.binary)
    inline, general = _placement(report, policy, opts.comment_style)
    bot = provider.whoami().username
    new_inline, _skipped = dedupe_against_existing(
        inline, provider.list_comments(ref), bot=bot
    )
    accepted, general, rejected_warnings, sent = _post_inline(
        provider,
        ref,
        head_sha,
        new_inline,
        inline,
        general,
        contributors,
        host,
        diff,
    )
    warnings.extend(rejected_warnings)
    posted = Posted(discussions=sent)
    verdict, withheld = _decide(
        considered,
        dropped_major=bool(dropped_major),
        capping=capping,
        incomplete=incomplete,
        opts=opts,
        floor=floor,
    )
    if not_reviewed:
        warnings.append(
            f"{len(not_reviewed)} file(s) not reviewed (truncated or binary)"
        )
    if capping:
        warnings.append(f"{len(capping)} truncated file(s); verdict capped at comment")
    if withheld and verdict is not Verdict.APPROVE:
        warnings.append("approve withheld: " + "; ".join(withheld))
    if opts.comment_style in ("summary", "both"):
        body = render_summary(
            agent,
            verdict,
            summary,
            accepted,
            general,
            warnings,
            head_sha,
            incomplete=incomplete,
            not_reviewed=not_reviewed,
            config_notes=notes,
            vcs_host=host,
        )
        provider.upsert_comment(ref, summary_marker(agent), body)
        posted = posted.model_copy(update={"notes": 1})
    state, description = _status_for(verdict, withheld, not_reviewed, incomplete)
    provider.set_status(ref.project, head_sha, state, context, description, "")
    posted = posted.model_copy(update={"status": state.value})
    if verdict is Verdict.APPROVE:
        warnings.extend(_approve(provider, ref, head_sha, verdict, opts))
    return PublishOutcome(
        posted,
        tuple(warnings),
        verdict,
        tuple(accepted),
        tuple(general),
    )


def _stamp_all(findings: Sequence[Finding], head_sha: str) -> list[Finding]:
    unique: dict[str, Finding] = {}
    for item in findings:
        stamped = item.model_copy(
            update={"file": normalise_path(item.file), "head_sha": head_sha, "id": ""}
        ).with_id()
        unique.setdefault(stamped.id, stamped)
    return list(unique.values())


def _decide(
    considered: Sequence[Finding],
    *,
    dropped_major: bool,
    capping: Sequence[str],
    incomplete: Mapping[str, str],
    opts: PublishOptions,
    floor: Verdict,
) -> tuple[Verdict, list[str]]:
    base = resolve_verdict(
        considered,
        incomplete=tuple(incomplete),
        major_threshold=opts.major_threshold,
        floor=floor,
    )
    withheld: list[str] = []
    verdict = base
    if dropped_major and verdict is Verdict.APPROVE:
        withheld.append("a blocking or major finding is outside the change")
        verdict = _lift(verdict, Verdict.COMMENT)
    if capping:
        verdict = _clamp(verdict, "comment", "truncated files not reviewed", withheld)
    if opts.verdict_cap is not None:
        reason = opts.verdict_cap_reason or "verdict capped"
        verdict = _clamp(verdict, opts.verdict_cap, reason, withheld)
    return verdict, withheld


def _clamp(verdict: Verdict, cap: str, reason: str, withheld: list[str]) -> Verdict:
    capped = _capped(verdict, Verdict(cap))
    if capped is not verdict and verdict is Verdict.APPROVE:
        withheld.append(reason)
    return capped


def _capped(computed: Verdict, cap: Verdict) -> Verdict:
    if _VERDICT_RANK[computed] <= _VERDICT_RANK[cap]:
        return computed
    return cap


def _status_for(
    verdict: Verdict,
    withheld: Sequence[str],
    not_reviewed: Sequence[str],
    incomplete: Mapping[str, str],
) -> tuple[StatusState, str]:
    if verdict is Verdict.COMMENT and withheld:
        state = StatusState.PENDING
        text = "approve withheld: " + "; ".join(withheld)
    elif verdict is Verdict.INCOMPLETE:
        state = StatusState.PENDING
        text = "review incomplete: " + ", ".join(sorted(incomplete))
    else:
        state, text = _STATUS[verdict]
    if not_reviewed and "not reviewed" not in text:
        text = f"{text}; {len(not_reviewed)} file(s) not reviewed"
    return state, text[:_MAX_DESCRIPTION]


def _post_inline(
    provider: VcsProvider,
    ref: ChangeRequestRef,
    head_sha: str,
    new_inline: Sequence[Finding],
    inline: Sequence[Finding],
    general: list[tuple[Finding, str]],
    contributors: Mapping[str, tuple[str, ...]],
    host: str | None,
    diff: Sequence[FileDiff],
) -> tuple[list[Finding], list[tuple[Finding, str]], list[str], int]:
    """Post new inline comments; a comment the VCS rejects becomes a general note."""
    rejected: set[str] = set()
    warnings: list[str] = []
    if new_inline:
        by_path = {item.path: item for item in diff}
        comments = [
            InlineComment(
                item.file,
                item.line_end,
                render_inline_body(item, contributors.get(item.id), vcs_host=host),
                old_path=by_path[item.file].old_path if item.file in by_path else None,
                start_line=item.line_start
                if item.line_end != item.line_start
                else None,
            )
            for item in new_inline
        ]
        ids = provider.post_inline_comments(
            ref, head_sha, comments, provider.get_diff_refs(ref)
        )
        for index, item in enumerate(new_inline):
            if index < len(ids) and ids[index]:
                continue
            rejected.add(item.id)
            general.append((item, _REJECTED_NOTE))
            warnings.append(
                f"inline comment rejected by the VCS for {_code(item.file)}:"
                f"{item.line_end}; posted as a general note"
            )
    sent = len(new_inline) - len(rejected)
    accepted = [item for item in inline if item.id not in rejected]
    return accepted, general, warnings, sent


def _placement(
    report: AnchorReport,
    policy: PolicyResult,
    style: CommentStyle,
) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    inline: list[Finding] = []
    general: list[tuple[Finding, str]] = list(report.general)
    for finding, _reason in report.inline:
        if style == "summary":
            general.append((finding, _INLINE_DISABLED))
        elif finding.id in policy.summary_only:
            general.append(
                (finding, policy.reasons.get(finding.id, _SUMMARY_ONLY_LIMIT))
            )
        else:
            inline.append(finding)
    return inline, general


def _dropped_warnings(
    dropped: Sequence[tuple[Finding, str]], host: str | None
) -> list[str]:
    return [
        f"dropped {item.severity.value} finding, file not in the change: "
        f"{_code(item.file)}:{item.line_start} "
        f"{neutralise_markdown(item.title, vcs_host=host)[:120]}"
        for item, _reason in dropped
    ]


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
