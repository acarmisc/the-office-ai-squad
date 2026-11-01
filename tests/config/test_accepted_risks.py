from __future__ import annotations

from datetime import date
from typing import Any

from code_squad._common.accepted_risks import accepted_risk_filter
from code_squad._common.config.schema import AcceptedRisk
from code_squad._common.contract import Finding
from tests.support import finding_dict

TODAY = date(2026, 10, 31)


def _risk(**overrides: Any) -> AcceptedRisk:
    values: dict[str, Any] = {
        "id": "CVE-2024-1",
        "reason": "vendor patch pending",
        "expires": date(2099, 1, 1),
    }
    values.update(overrides)
    return AcceptedRisk.model_validate(values)


def _finding(**overrides: Any) -> Finding:
    values: dict[str, Any] = {"agent": "dwight", "severity": "major"}
    values.update(overrides)
    return Finding.model_validate(finding_dict(**values))


def test_matching_rule_id_is_dropped_and_a_note_names_the_reason() -> None:
    finding = _finding(rule_id="CVE-2024-1", file="package.json")
    kept, notes = accepted_risk_filter([_risk()], TODAY)([finding])
    assert kept == []
    assert len(notes) == 1
    assert "CVE-2024-1" in notes[0] and "vendor patch pending" in notes[0]


def test_a_reference_naming_the_advisory_also_matches() -> None:
    finding = _finding(
        rule_id="DWIGHT-DEP-001",
        references=["https://osv.dev/vulnerability/CVE-2024-1"],
    )
    kept, _ = accepted_risk_filter([_risk()], TODAY)([finding])
    assert kept == []


def test_unrelated_findings_are_kept_without_notes() -> None:
    finding = _finding(rule_id="SEC-XSS-001")
    kept, notes = accepted_risk_filter([_risk()], TODAY)([finding])
    assert kept == [finding]
    assert notes == []


def test_path_scope_only_drops_findings_under_that_path() -> None:
    risk = _risk(path="services/payments/**")
    inside = _finding(rule_id="CVE-2024-1", file="services/payments/pom.xml")
    outside = _finding(rule_id="CVE-2024-1", file="services/web/package.json")
    kept, _ = accepted_risk_filter([risk], TODAY)([inside, outside])
    assert kept == [outside]


def test_package_scope_needs_the_package_named_in_the_finding() -> None:
    risk = _risk(package="lodash")
    lodash = _finding(rule_id="CVE-2024-1", title="lodash prototype pollution")
    other = _finding(rule_id="CVE-2024-1", title="minimist prototype pollution")
    kept, _ = accepted_risk_filter([risk], TODAY)([lodash, other])
    assert kept == [other]


def test_expired_risks_do_not_drop_anything() -> None:
    finding = _finding(rule_id="CVE-2024-1")
    risk = _risk(expires=date(2026, 1, 1))
    kept, notes = accepted_risk_filter([risk], TODAY)([finding])
    assert kept == [finding]
    assert notes == []
