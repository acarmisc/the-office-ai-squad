"""Merge specialist outcomes into one consolidated report and render michael's body.

Verdict policy (shared with ``findings.resolve_verdict``): a specialist that did not
complete makes the review incomplete. A blocker still requests changes, and the warning
names the agents that failed; without a blocker the verdict is ``incomplete``, never
success. Otherwise the findings decide, and the result is never more lenient than the
verdict of a complete specialist, or than the high-risk rule that any major finding
requests changes. The verdict line itself is rendered by ``findings.publish`` once the
final verdict is known.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from code_squad._common.contract import Finding, Severity, Verdict, severity_rank
from code_squad._common.findings import (
    dedupe_findings,
    neutralise_markdown,
    normalise_path,
    resolve_verdict,
)
from code_squad.michael.fanout import SpecialistOutcome
from code_squad.michael.risk import RiskAssessment

_TOP_FINDINGS: Final = 20
_MAX_NARRATIVE: Final = 1500
_NO_FINDINGS: Final = "No findings were reported by the specialists that completed."
_SEVERITIES: Final = (Severity.BLOCKER, Severity.MAJOR, Severity.MINOR, Severity.NIT)


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
    floor: Verdict = Verdict.APPROVE

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
    for outcome in outcomes.values():
        if outcome.result is None:
            continue
        collected.extend(_stamped(item, head_sha) for item in outcome.result.findings)
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
    if failed:
        notes.append(f"incomplete: {', '.join(sorted(failed))} failed")
    floor = _floor(outcomes, findings, risk)
    return ConsolidatedReport(
        verdict=resolve_verdict(
            findings,
            incomplete=tuple(failed),
            major_threshold=major_threshold,
            floor=floor,
        ),
        findings=findings,
        contributors=contributors,
        statuses={agent: outcome.status for agent, outcome in outcomes.items()},
        failed=failed,
        risk=risk,
        head_sha=head_sha,
        warnings=tuple(notes),
        floor=floor,
    )


def _stamped(finding: Finding, head_sha: str) -> Finding:
    return finding.model_copy(
        update={"file": normalise_path(finding.file), "head_sha": head_sha, "id": ""}
    ).with_id()


def _floor(
    outcomes: Mapping[str, SpecialistOutcome],
    findings: Sequence[Finding],
    risk: RiskAssessment,
) -> Verdict:
    floor = Verdict.APPROVE
    for outcome in outcomes.values():
        if outcome.result is None or not outcome.complete:
            continue
        if outcome.result.verdict is Verdict.REQUEST_CHANGES:
            floor = Verdict.REQUEST_CHANGES
        elif outcome.result.verdict is Verdict.COMMENT and floor is Verdict.APPROVE:
            floor = Verdict.COMMENT
    majors = sum(1 for item in findings if item.severity is Severity.MAJOR)
    if risk.tier == "high" and majors >= 1:
        floor = Verdict.REQUEST_CHANGES
    return floor


def render_summary(
    report: ConsolidatedReport,
    *,
    intent: str,
    changed_files: int,
    stacks: Sequence[str],
    narrative: str | None = None,
) -> str:
    """Michael's body: facts, optional narrative, specialists and findings.

    The header, verdict line, general notes and marker come from ``findings.publish``.
    """
    lines = [
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
    return "\n".join(lines)


def _findings_table(report: ConsolidatedReport) -> list[str]:
    if not report.findings:
        return [_NO_FINDINGS]
    counts = Counter(item.severity for item in report.findings)
    tally = ", ".join(f"{sev.value} {counts.get(sev, 0)}" for sev in _SEVERITIES)
    rows = [
        f"Findings: {len(report.findings)} total ({tally}).",
        "",
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
        hidden = len(report.findings) - _TOP_FINDINGS
        rows.append(f"| | {hidden} more not shown | | |")
    return rows


def _cell(text: str, limit: int = 160) -> str:
    flat = neutralise_markdown(" ".join(str(text).split())[:limit])
    return flat.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def _narrative(text: str) -> str:
    clipped = " ".join(text.split())[:_MAX_NARRATIVE]
    return neutralise_markdown(clipped).replace("<", "&lt;").replace(">", "&gt;")
