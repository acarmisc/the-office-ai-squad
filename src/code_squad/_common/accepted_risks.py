"""Accepted advisories applied to findings before publication (ADV-19).

A risk accepts a finding whose rule id, or one of whose references, names the risk id.
``package`` and ``path`` narrow the acceptance: the finding must name the package in
its text and sit under the glob. Expired risks accept nothing. Only the organisation
layer can add risks (``security.accepted_risks`` is org-only), so a repository cannot
make its own findings disappear.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import date
from typing import Final

from code_squad._common.config.globs import glob_match
from code_squad._common.config.schema import AcceptedRisk
from code_squad._common.contract import Finding

PrePublishFilter = Callable[[Sequence[Finding]], tuple[list[Finding], list[str]]]
_BOUNDARY_BEFORE: Final = r"(?<![A-Za-z0-9])"
_BOUNDARY_AFTER: Final = r"(?![A-Za-z0-9])"


def accepted_risk_filter(
    risks: Sequence[AcceptedRisk], today: date
) -> PrePublishFilter:
    """Return a filter that drops accepted findings and reports each drop."""
    active = tuple(risk for risk in risks if risk.expires >= today)

    def apply(findings: Sequence[Finding]) -> tuple[list[Finding], list[str]]:
        kept: list[Finding] = []
        notes: list[str] = []
        for finding in findings:
            risk = _accepting(finding, active)
            if risk is None:
                kept.append(finding)
            else:
                notes.append(
                    f"accepted risk: {risk.id} until {risk.expires.isoformat()}: "
                    f"{risk.reason}"
                )
        return kept, notes

    return apply


def _accepting(finding: Finding, risks: Sequence[AcceptedRisk]) -> AcceptedRisk | None:
    for risk in risks:
        if not _names(finding, risk.id):
            continue
        if risk.path is not None and not glob_match(risk.path, finding.file):
            continue
        if risk.package is not None and not _mentions(_text(finding), risk.package):
            continue
        return risk
    return None


def _names(finding: Finding, identifier: str) -> bool:
    if finding.rule_id == identifier:
        return True
    return any(_mentions(reference, identifier) for reference in finding.references)


def _text(finding: Finding) -> str:
    return " ".join(
        [finding.title, finding.rationale, finding.file, *finding.references]
    )


def _mentions(text: str, identifier: str) -> bool:
    pattern = _BOUNDARY_BEFORE + re.escape(identifier) + _BOUNDARY_AFTER
    return re.search(pattern, text, re.IGNORECASE) is not None
