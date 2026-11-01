"""Merge specialist outcomes into one consolidated report and render its summary.

Verdict policy: any specialist that did not complete makes the verdict ``incomplete``,
which is never reported as success. Otherwise the findings decide: a blocker requests
changes; in the high risk tier any major finding requests changes; other majors follow
``major_threshold`` as in the findings pipeline. The result is never more lenient than
the verdict of any complete specialist, so a verdict a specialist withheld (for example
through its own verdict cap) is not lost in the merge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from code_squad._common.contract import Finding, Severity, Verdict, severity_rank
from code_squad._common.findings import compute_verdict, dedupe_findings, summary_marker
from code_squad.michael.fanout import SpecialistOutcome
from code_squad.michael.risk import RiskAssessment

_TOP_FINDINGS: Final = 10
_MAX_NARRATIVE: Final = 1500
_NO_FINDINGS: Final = "No findings were reported by the specialists that completed."


@dataclass(frozen=True)
class ConsolidatedReport:
    verdict: Verdict
    findings: tuple[Finding, ...]
    contributors: dict[str, tuple[str, ...]]
    statuses: dict[str, str]
    failed: dict[str, str]
    risk: RiskAssessment
    head_sha: str
    warnings: tuple[str, ...]

    @property
    def agents_run(self) -> tuple[str, ...]:
        return tuple(self.statuses)


def aggregate(
    outcomes: Mapping[str, SpecialistOutcome],
    *,
    head_sha: str,
    risk: RiskAssessment,
    major_threshold: int,
    warnings: Sequence[str] = (),
) -> ConsolidatedReport:
    notes = list(warnings)
    collected: list[Finding] = []
    for agent, outcome in outcomes.items():
        if outcome.result is None:
            continue
        for finding in outcome.result.findings:
            if finding.head_sha != head_sha:
                notes.append(
                    f"{agent}: a finding for another head was dropped "
                    f"({finding.rule_id})"
                )
                continue
            collected.append(finding)
    merged = sorted(
        dedupe_findings(collected),
        key=lambda item: (
            -severity_rank(item.finding.severity),
            item.finding.file,
            item.finding.line_start,
        ),
    )
    findings = tuple(item.finding for item in merged)
    contributors = {item.finding.id: item.contributors for item in merged}
    failed = {
        agent: outcome.error or outcome.status
        for agent, outcome in outcomes.items()
        if not outcome.complete
    }
    floors = [
        outcome.result.verdict
        for outcome in outcomes.values()
        if outcome.result is not None and outcome.complete
    ]
    return ConsolidatedReport(
        verdict=_verdict(findings, failed, risk, major_threshold, floors),
        findings=findings,
        contributors=contributors,
        statuses={agent: outcome.status for agent, outcome in outcomes.items()},
        failed=failed,
        risk=risk,
        head_sha=head_sha,
        warnings=tuple(notes),
    )


def _verdict(
    findings: Sequence[Finding],
    failed: Mapping[str, str],
    risk: RiskAssessment,
    major_threshold: int,
    floors: Sequence[Verdict],
) -> Verdict:
    if failed:
        return Verdict.INCOMPLETE
    majors = sum(1 for item in findings if item.severity is Severity.MAJOR)
    if risk.tier == "high" and majors >= 1:
        computed = Verdict.REQUEST_CHANGES
    else:
        computed = compute_verdict(list(findings), major_threshold)
    return max([computed, *floors], key=_RANK.__getitem__)


_RANK: Final[dict[Verdict, int]] = {
    Verdict.APPROVE: 0,
    Verdict.COMMENT: 1,
    Verdict.REQUEST_CHANGES: 2,
    Verdict.INCOMPLETE: 3,
}


def render_summary(
    report: ConsolidatedReport,
    *,
    intent: str,
    changed_files: int,
    stacks: Sequence[str],
    narrative: str | None = None,
) -> str:
    lines = [
        "### Review by `michael`",
        "",
        _verdict_line(report),
        "",
        f"Reviewed: {changed_files} changed file(s) at head `{report.head_sha[:12]}`. "
        f"Intent: `{intent}`. Stacks: {', '.join(stacks) or 'none detected'}.",
        f"Risk: **{report.risk.tier}**"
        + (
            f" ({'; '.join(_cell(item, 200) for item in report.risk.reasons)})"
            if report.risk.reasons
            else " (no risk signals)"
        )
        + ".",
    ]
    if narrative:
        lines += [
            "",
            "#### Narrative (generated, not authoritative)",
            "",
            _narrative(narrative),
        ]
    lines += [
        "",
        "#### Specialists",
        "",
        "| Agent | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for agent, status in report.statuses.items():
        detail = _cell(report.failed.get(agent, "")) or "reported"
        lines.append(f"| `{_cell(agent, 40)}` | {status} | {detail} |")
    lines += ["", "#### Findings", ""]
    lines += _findings_table(report)
    if report.warnings:
        lines += [
            "",
            "#### Warnings",
            *[f"- {_cell(item, 300)}" for item in report.warnings],
        ]
    lines += ["", summary_marker("michael")]
    return "\n".join(lines)


def _verdict_line(report: ConsolidatedReport) -> str:
    head = report.head_sha[:12]
    if report.verdict is not Verdict.INCOMPLETE:
        return f"Verdict: **{report.verdict.value}** at head `{head}`."
    names = ", ".join(
        f"`{_cell(agent, 40)}` ({_cell(reason, 120)})"
        for agent, reason in report.failed.items()
    )
    return (
        f"Verdict: **incomplete** at head `{head}`. The verdict is not final because "
        f"these specialists did not complete: {names}. Re-run the review for a final "
        "verdict."
    )


def _findings_table(report: ConsolidatedReport) -> list[str]:
    if not report.findings:
        return [_NO_FINDINGS]
    rows = [
        "| Severity | Finding | Location | Reported by |",
        "| --- | --- | --- | --- |",
    ]
    for finding in report.findings[:_TOP_FINDINGS]:
        agents = ", ".join(report.contributors.get(finding.id, (finding.agent,)))
        location = f"{_cell(finding.file, 200)}:{finding.line_start}"
        rows.append(
            f"| {finding.severity.value} | {_cell(finding.title)} | {location} "
            f"| {_cell(agents, 120)} |"
        )
    if len(report.findings) > _TOP_FINDINGS:
        rows.append(f"| | {len(report.findings) - _TOP_FINDINGS} more not shown | | |")
    return rows


def _cell(text: str, limit: int = 160) -> str:
    flat = " ".join(str(text).split())[:limit]
    return flat.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def _narrative(text: str) -> str:
    clipped = " ".join(text.split())[:_MAX_NARRATIVE]
    return clipped.replace("<", "&lt;").replace(">", "&gt;")
