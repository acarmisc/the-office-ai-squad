from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from code_squad.dwight.scanners import (
    GitleaksScanner,
    ScannerNotConfiguredError,
    ScannerOutputError,
    SemgrepScanner,
    TrivyFsScanner,
)
from tests.dwight.helpers import fixture_text

WORKDIR = Path("/tmp/scan-target")
RULES = Path("/opt/rules/pinned")


def test_gitleaks_argv_is_pinned_and_redacted() -> None:
    argv = GitleaksScanner().command(WORKDIR)
    assert argv[:3] == ["gitleaks", "dir", str(WORKDIR)]
    assert "--redact" in argv
    assert argv[argv.index("--report-format") + 1] == "json"
    assert argv[argv.index("--exit-code") + 1] == "0"


def test_gitleaks_normalise_never_carries_the_secret_value() -> None:
    findings = GitleaksScanner().normalise(fixture_text("gitleaks_report.json"))
    assert len(findings) == 1
    finding = findings[0]
    assert finding["rule_id"] == "generic-api-key"
    assert finding["file"] == "config/settings.py"
    assert finding["line"] == 12
    assert finding["location_only"] is True
    assert "fake-token-for-tests" not in json.dumps(findings)


def test_semgrep_argv_uses_local_rules_and_disables_metrics() -> None:
    argv = SemgrepScanner(RULES).command(WORKDIR)
    assert argv[argv.index("--config") + 1] == str(RULES)
    assert "--json" in argv and "--metrics=off" in argv


def test_semgrep_normalise_maps_severity_and_cwe() -> None:
    findings = SemgrepScanner(RULES).normalise(fixture_text("semgrep_report.json"))
    assert [f["severity"] for f in findings] == ["major", "minor"]
    assert findings[0]["cwe"] == ["CWE-79: Improper Neutralization of Input"]
    assert findings[1]["cwe"] == ["CWE-489"]
    assert findings[0]["line"] == 8


def test_trivy_argv_limits_scanners_and_skips_db_update() -> None:
    argv = TrivyFsScanner().command(WORKDIR)
    assert argv[:2] == ["trivy", "fs"]
    assert argv[argv.index("--scanners") + 1] == "vuln,secret"
    assert "--skip-db-update" in argv


def test_trivy_normalise_covers_vulnerabilities_and_secrets_location_only() -> None:
    findings = TrivyFsScanner().normalise(fixture_text("trivy_report.json"))
    vuln = next(f for f in findings if f["category"] == "dependency")
    assert vuln["rule_id"] == "CVE-2021-23337"
    assert vuln["fixed_version"] == "4.17.21"
    assert vuln["severity"] == "major"
    secret = next(f for f in findings if f["category"] == "secrets")
    assert secret["location_only"] is True
    assert "ghp_fake" not in json.dumps(findings)


def test_non_json_output_is_rejected() -> None:
    with pytest.raises(ScannerOutputError):
        SemgrepScanner(RULES).normalise("not json")


def test_empty_scanner_output_fails_closed_instead_of_meaning_clean() -> None:
    with pytest.raises(ScannerOutputError):
        TrivyFsScanner().normalise("")


def test_run_needs_an_injected_executor() -> None:
    with pytest.raises(ScannerNotConfiguredError):
        GitleaksScanner().run(WORKDIR)


def test_run_passes_argv_to_executor_and_normalises_its_output() -> None:
    seen: list[list[str]] = []

    def executor(argv: Sequence[str]) -> str:
        seen.append(list(argv))
        return fixture_text("trivy_report.json")

    findings = TrivyFsScanner(executor=executor).run(WORKDIR)
    assert seen and seen[0][:2] == ["trivy", "fs"]
    assert len(findings) == 2


def test_availability_follows_path_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert not GitleaksScanner().available()
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    assert SemgrepScanner(RULES).available()
