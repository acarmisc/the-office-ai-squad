from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from code_squad._common.contract import Confidence, Severity

RankKey = tuple[int, float, float]
_NO_EPSS: Final = 0.0


@dataclass(frozen=True)
class SeverityThresholds:
    kev_is_blocker: bool = True
    epss_major: float = 0.1
    cvss_blocker: float = 9.0
    cvss_major: float = 7.0
    cvss_minor: float = 4.0


def rank_key(*, kev: bool, epss: float | None, cvss: float | None) -> RankKey:
    return (1 if kev else 0, epss if epss is not None else _NO_EPSS, cvss or 0.0)


def suggested_severity(
    *,
    kev: bool,
    epss: float | None,
    cvss: float | None,
    thresholds: SeverityThresholds,
) -> Severity:
    if kev and thresholds.kev_is_blocker:
        return Severity.BLOCKER
    if cvss is not None and cvss >= thresholds.cvss_blocker:
        return Severity.BLOCKER
    if (cvss is not None and cvss >= thresholds.cvss_major) or (
        epss is not None and epss >= thresholds.epss_major
    ):
        return Severity.MAJOR
    if cvss is not None and cvss >= thresholds.cvss_minor:
        return Severity.MINOR
    return Severity.NIT


def suggested_confidence(*, verified: bool) -> Confidence:
    return Confidence.MEDIUM if verified else Confidence.LOW
