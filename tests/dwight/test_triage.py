from __future__ import annotations

from code_squad._common.contract import Confidence, Severity
from code_squad.dwight.intel.triage import (
    SeverityThresholds,
    rank_key,
    suggested_confidence,
    suggested_severity,
)

DEFAULTS = SeverityThresholds()


def test_ranking_puts_kev_first_then_epss_then_cvss() -> None:
    candidates = {
        "cvss-only-critical": rank_key(kev=False, epss=None, cvss=9.8),
        "kev-low-cvss": rank_key(kev=True, epss=None, cvss=5.0),
        "high-epss-medium": rank_key(kev=False, epss=0.9, cvss=6.5),
        "low-epss-high-cvss": rank_key(kev=False, epss=0.2, cvss=7.5),
    }
    ordered = sorted(candidates, key=lambda name: candidates[name], reverse=True)
    assert ordered == [
        "kev-low-cvss",
        "high-epss-medium",
        "low-epss-high-cvss",
        "cvss-only-critical",
    ]


def test_kev_is_a_blocker_regardless_of_cvss() -> None:
    severity = suggested_severity(kev=True, epss=None, cvss=5.0, thresholds=DEFAULTS)
    assert severity is Severity.BLOCKER


def test_cvss_bands_and_epss_threshold_map_to_severity() -> None:
    assert (
        suggested_severity(kev=False, epss=None, cvss=9.8, thresholds=DEFAULTS)
        is Severity.BLOCKER
    )
    assert (
        suggested_severity(kev=False, epss=None, cvss=7.0, thresholds=DEFAULTS)
        is Severity.MAJOR
    )
    assert (
        suggested_severity(kev=False, epss=0.15, cvss=None, thresholds=DEFAULTS)
        is Severity.MAJOR
    )
    assert (
        suggested_severity(kev=False, epss=None, cvss=5.0, thresholds=DEFAULTS)
        is Severity.MINOR
    )
    assert (
        suggested_severity(kev=False, epss=0.01, cvss=None, thresholds=DEFAULTS)
        is Severity.NIT
    )


def test_thresholds_are_configurable() -> None:
    relaxed = SeverityThresholds(kev_is_blocker=False, cvss_blocker=10.1)
    assert (
        suggested_severity(kev=True, epss=None, cvss=5.0, thresholds=relaxed)
        is Severity.MINOR
    )
    assert (
        suggested_severity(kev=False, epss=None, cvss=9.8, thresholds=relaxed)
        is Severity.MAJOR
    )


def test_confidence_drops_to_low_when_data_is_unverified() -> None:
    assert suggested_confidence(verified=True) is Confidence.MEDIUM
    assert suggested_confidence(verified=False) is Confidence.LOW
