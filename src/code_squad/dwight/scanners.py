from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, Protocol

Executor = Callable[[Sequence[str]], str]
Finding = dict[str, Any]

_TRIVY_SEVERITY: Final = {
    "CRITICAL": "blocker",
    "HIGH": "major",
    "MEDIUM": "minor",
    "LOW": "nit",
    "UNKNOWN": "nit",
}
_SEMGREP_SEVERITY: Final = {"ERROR": "major", "WARNING": "minor", "INFO": "nit"}


class ScannerError(Exception):
    """A local scanner could not produce usable findings."""


class ScannerNotConfiguredError(ScannerError):
    """No sandboxed executor was injected for the scanner."""


class ScannerOutputError(ScannerError):
    """Scanner output did not have the expected shape."""


class LocalScanner(Protocol):
    name: str
    binary: str

    def available(self) -> bool: ...

    def command(self, workdir: Path) -> list[str]: ...

    def normalise(self, raw: str) -> list[Finding]: ...

    def run(self, workdir: Path) -> list[Finding]: ...


class _BaseScanner:
    name: str
    binary: str

    def __init__(self, executor: Executor | None = None) -> None:
        self._executor = executor

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def run(self, workdir: Path) -> list[Finding]:
        if self._executor is None:
            raise ScannerNotConfiguredError(
                f"{self.name} needs a sandboxed executor; none was injected"
            )
        return self.normalise(self._executor(self.command(workdir)))

    def command(self, workdir: Path) -> list[str]:
        raise NotImplementedError

    def normalise(self, raw: str) -> list[Finding]:
        raise NotImplementedError


class GitleaksScanner(_BaseScanner):
    name = "gitleaks"
    binary = "gitleaks"

    def command(self, workdir: Path) -> list[str]:
        return [
            self.binary,
            "dir",
            str(workdir),
            "--report-format",
            "json",
            "--report-path",
            "-",
            "--redact",
            "--exit-code",
            "0",
        ]

    def normalise(self, raw: str) -> list[Finding]:
        rows = _load(self.name, raw, list)
        findings: list[Finding] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            findings.append(
                {
                    "scanner": self.name,
                    "category": "secrets",
                    "rule_id": _text(row.get("RuleID")),
                    "title": _text(row.get("Description")),
                    "file": _text(row.get("File")),
                    "line": _int(row.get("StartLine")),
                    "severity": "major",
                    "location_only": True,
                }
            )
        return findings


class SemgrepScanner(_BaseScanner):
    name = "semgrep"
    binary = "semgrep"

    def __init__(self, rules: Path, executor: Executor | None = None) -> None:
        super().__init__(executor)
        self._rules = rules

    def command(self, workdir: Path) -> list[str]:
        return [
            self.binary,
            "scan",
            "--config",
            str(self._rules),
            "--json",
            "--metrics=off",
            str(workdir),
        ]

    def normalise(self, raw: str) -> list[Finding]:
        data = _load(self.name, raw, dict)
        rows = data.get("results")
        if not isinstance(rows, list):
            raise ScannerOutputError("semgrep output has no results list")
        findings: list[Finding] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            extra = _dict(row.get("extra"))
            start = _dict(row.get("start"))
            level = _text(extra.get("severity"))
            findings.append(
                {
                    "scanner": self.name,
                    "category": "static-analysis",
                    "rule_id": _text(row.get("check_id")),
                    "title": _text(extra.get("message"))[:200],
                    "file": _text(row.get("path")),
                    "line": _int(start.get("line")),
                    "severity": _SEMGREP_SEVERITY.get(level, "nit"),
                    "cwe": _cwe_list(extra.get("metadata")),
                    "location_only": False,
                }
            )
        return findings


class TrivyFsScanner(_BaseScanner):
    name = "trivy"
    binary = "trivy"

    def command(self, workdir: Path) -> list[str]:
        return [
            self.binary,
            "fs",
            "--format",
            "json",
            "--scanners",
            "vuln,secret",
            "--skip-db-update",
            "--quiet",
            str(workdir),
        ]

    def normalise(self, raw: str) -> list[Finding]:
        data = _load(self.name, raw, dict)
        results = data.get("Results")
        if not isinstance(results, list):
            return []
        findings: list[Finding] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            target = _text(result.get("Target"))
            for vuln in _rows(result.get("Vulnerabilities")):
                findings.append(_trivy_vuln(self.name, target, vuln))
            for secret in _rows(result.get("Secrets")):
                findings.append(_trivy_secret(self.name, target, secret))
        return findings


def _trivy_vuln(scanner: str, target: str, vuln: dict[str, Any]) -> Finding:
    return {
        "scanner": scanner,
        "category": "dependency",
        "rule_id": _text(vuln.get("VulnerabilityID")),
        "title": _text(vuln.get("Title"))[:200],
        "file": target,
        "package": _text(vuln.get("PkgName")),
        "installed_version": _text(vuln.get("InstalledVersion")),
        "fixed_version": _text(vuln.get("FixedVersion")),
        "severity": _TRIVY_SEVERITY.get(_text(vuln.get("Severity")), "nit"),
        "location_only": False,
    }


def _trivy_secret(scanner: str, target: str, secret: dict[str, Any]) -> Finding:
    return {
        "scanner": scanner,
        "category": "secrets",
        "rule_id": _text(secret.get("RuleID")),
        "title": _text(secret.get("Title"))[:200],
        "file": target,
        "line": _int(secret.get("StartLine")),
        "severity": "major",
        "location_only": True,
    }


def _load(scanner: str, raw: str, expected: type) -> Any:
    try:
        data = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError as exc:
        raise ScannerOutputError(f"{scanner} output is not JSON") from exc
    if data is None and expected is list:
        return []
    if not isinstance(data, expected):
        raise ScannerOutputError(f"{scanner} output has an unexpected shape")
    return data


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _cwe_list(metadata: Any) -> list[str]:
    if not isinstance(metadata, dict):
        return []
    raw = metadata.get("cwe")
    values = raw if isinstance(raw, list) else [raw]
    return [v for v in values if isinstance(v, str)]
