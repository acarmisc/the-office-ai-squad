from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from typing import Any, Final, Protocol, runtime_checkable

from strands import tool

from code_squad._common.context import current
from code_squad._common.untrusted import wrap_untrusted
from code_squad.dwight.deps.model import ECOSYSTEMS, Ecosystem, Package
from code_squad.dwight.deps.parsers import is_manifest, parse_file
from code_squad.dwight.intel.ids import is_cve_id, is_iso_date
from code_squad.dwight.intel.service import (
    AdvisoryResult,
    CveReport,
    IntelService,
    LookupResult,
    VulnMatch,
)

UNAVAILABLE_PREFIX: Final = "VULNERABILITY DATA UNAVAILABLE/UNVERIFIED"
INCOMPLETE_FLAG: Final = "intel_incomplete"
ROOT_MANIFESTS: Final = (
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pom.xml",
    "gradle.lockfile",
    "build.gradle",
    "build.gradle.kts",
    "requirements.txt",
    "uv.lock",
    "Dockerfile",
)
MAX_PACKAGES: Final = 200
MAX_ADVISORY_ROWS: Final = 25
MAX_QUERY_CHARS: Final = 200
_ECOSYSTEM_INPUT: Final[dict[str, Ecosystem]] = {
    name.lower(): name for name in ECOSYSTEMS
}
_PACKAGE_NAME: Final = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._/@:+-]{0,213}$")
_VERSION: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:@~=-]{0,127}$")


@runtime_checkable
class RepoFiles(Protocol):
    def changed_files(self) -> list[str]: ...

    def read(self, path: str, ref: str) -> str: ...


@tool
def parse_dependencies(ref: str = "") -> str:
    """Parse dependency manifests and lockfiles of this review into a package list.

    Uses the manifests changed in the review. If none changed, looks for the
    well-known manifest names at the repository root. Output lists every package
    with ecosystem, name, version, pinned flag and location, plus warnings and
    the unpinned packages.

    Args:
        ref: Git ref to read the files from. Empty means the review head.
    """
    repo = _repo_files()
    if repo is None:
        return "repository files are not available for this review"
    scope, paths = _manifest_paths(repo)
    if not paths:
        return "no dependency manifests found for this review"
    packages: list[Package] = []
    warnings: list[str] = []
    read_paths: list[str] = []
    for path in paths:
        text = _read_or_none(repo, path, ref)
        if text is None:
            continue
        read_paths.append(path)
        result = parse_file(path, text)
        packages.extend(result.packages)
        warnings.extend(result.warnings)
    payload = {
        "scope": scope,
        "files": read_paths,
        "packages": [_package_json(p) for p in packages],
        "unpinned": [
            _package_json(p) for p in packages if p.version is None or not p.pinned
        ],
        "warnings": warnings,
    }
    return wrap_untrusted(
        json.dumps(payload, indent=2, sort_keys=True), "repo-manifests"
    )


@tool
def lookup_vulnerabilities(packages: list[dict[str, Any]]) -> str:
    """Look up known vulnerabilities for packages in OSV, with GHSA as secondary source.

    Each package needs ecosystem (npm, Maven, PyPI or Docker), name and version.
    Results are ranked KEV first, then EPSS, then CVSS. Reachability is not decided
    here: check in the code whether the vulnerable code path is used.

    Args:
        packages: Package objects with keys ecosystem, name, version and optionally
            source_file.
    """
    intel = _intel()
    if intel is None:
        return "vulnerability intelligence is not configured"
    parsed, rejected = _package_inputs(packages)
    result = intel.lookup_vulnerabilities(parsed)
    return _render_lookup(result, rejected)


@tool
def lookup_cve(cve_id: str) -> str:
    """Look up one CVE in NVD and enrich it with CISA KEV membership and EPSS.

    Args:
        cve_id: CVE identifier in the form CVE-YYYY-NNNN.
    """
    if not is_cve_id(cve_id):
        return "invalid CVE id; expected the form CVE-YYYY-NNNN"
    intel = _intel()
    if intel is None:
        return "vulnerability intelligence is not configured"
    return _render_cve(intel.lookup_cve(cve_id))


@tool
def search_advisories(query: str, ecosystem: str = "", since: str = "") -> str:
    """Search recent reviewed GitHub Security Advisories by keyword.

    Args:
        query: Keyword matched against advisory id, CVE, summary and package names.
        ecosystem: Optional ecosystem: npm, Maven, PyPI or Docker (Docker has no feed).
        since: Optional lower bound on publication date, YYYY-MM-DD.
    """
    text = query.strip()
    if not text or len(text) > MAX_QUERY_CHARS:
        return f"query must be 1 to {MAX_QUERY_CHARS} characters"
    eco = _ecosystem_or_none(ecosystem)
    if ecosystem and eco is None:
        return "unsupported ecosystem; use npm, Maven, PyPI or Docker"
    if since and not is_iso_date(since):
        return "since must be a YYYY-MM-DD date"
    intel = _intel()
    if intel is None:
        return "vulnerability intelligence is not configured"
    result = intel.search_advisories(text, ecosystem=eco, since=since or None)
    return _render_search(result)


def _intel() -> IntelService | None:
    service = current().services.get("intel")
    return service if isinstance(service, IntelService) else None


def _repo_files() -> RepoFiles | None:
    service = current().services.get("repo_files")
    return service if isinstance(service, RepoFiles) else None


def _manifest_paths(repo: RepoFiles) -> tuple[str, list[str]]:
    changed = [path for path in repo.changed_files() if is_manifest(path)]
    if changed:
        return "changed", changed
    return "root", list(ROOT_MANIFESTS)


def _read_or_none(repo: RepoFiles, path: str, ref: str) -> str | None:
    try:
        return repo.read(path, ref)
    except (FileNotFoundError, KeyError):
        return None


def _package_json(package: Package) -> dict[str, Any]:
    return {
        "ecosystem": package.ecosystem,
        "name": package.name,
        "version": package.version,
        "pinned": package.pinned,
        "source_file": package.source_file,
        "line": package.line,
        "direct": package.direct,
    }


def _package_inputs(raw: Sequence[Any]) -> tuple[list[Package], list[str]]:
    packages: list[Package] = []
    rejected: list[str] = []
    for index, entry in enumerate(raw):
        if len(packages) >= MAX_PACKAGES:
            rejected.append(f"more than {MAX_PACKAGES} packages; the rest were skipped")
            break
        package, reason = _package_input(entry)
        if package is None:
            rejected.append(f"entry {index} rejected: {reason}")
        else:
            packages.append(package)
    return packages, rejected


def _package_input(entry: Any) -> tuple[Package | None, str]:
    if not isinstance(entry, dict):
        return None, "not an object"
    ecosystem = _ecosystem_or_none(str(entry.get("ecosystem", "")))
    if ecosystem is None:
        return None, "unsupported ecosystem"
    name = entry.get("name")
    if not isinstance(name, str) or not _PACKAGE_NAME.match(name):
        return None, "invalid name"
    version = entry.get("version")
    if version is not None and (
        not isinstance(version, str) or not _VERSION.match(version)
    ):
        return None, "invalid version"
    source = entry.get("source_file")
    source_file = source if isinstance(source, str) and source else "model-input"
    return (
        Package(
            ecosystem=ecosystem,
            name=name,
            version=version,
            pinned=version is not None,
            source_file=source_file[:300],
            line=None,
            direct=None,
        ),
        "",
    )


def _ecosystem_or_none(value: str) -> Ecosystem | None:
    return _ECOSYSTEM_INPUT.get(value.strip().lower())


def _render_lookup(result: LookupResult, rejected: Iterable[str]) -> str:
    lines = _incomplete_lines(result.unavailable)
    if result.items:
        lines.append(
            f"{len(result.items)} vulnerability match(es), ranked KEV, EPSS, CVSS:"
        )
        for match in result.items:
            lines.extend(_match_lines(match))
    else:
        lines.append("no known vulnerabilities returned for the checked packages")
    lines.extend(_notes(result.warnings, rejected))
    return "\n".join(lines)


def _match_lines(match: VulnMatch) -> list[str]:
    package = match.package
    lines = [
        f"- {package.ecosystem} {package.name}@{package.version}"
        f" ({package.source_file})",
        f"  id: {match.vuln_id}  cve: {match.cve_id or 'none'}  source: {match.source}"
        f"  verified: {_yes(match.verified)}",
        f"  kev: {_yes(match.kev)}  epss: {_score(match.epss)}"
        f"  percentile: {_score(match.epss_percentile)}"
        f"  cvss: {_score(match.cvss)} ({match.cvss_source or 'unknown'})",
        f"  suggested severity: {match.suggested_severity.value}"
        f"  confidence: {match.suggested_confidence.value}",
        f"  fixed versions: {', '.join(match.fixed_versions) or 'none listed'}",
        f"  cwe: {', '.join(match.cwe_ids) or 'none'}",
    ]
    if match.summary:
        lines.append("  summary: " + wrap_untrusted(match.summary, match.source))
    for url in match.references:
        lines.append("  reference: " + wrap_untrusted(url, match.source))
    return lines


def _render_cve(report: CveReport) -> str:
    lines = _incomplete_lines(report.unavailable)
    lines.append(f"CVE {report.cve_id}")
    kev = report.kev
    if kev is None:
        lines.append("  kev: no")
    else:
        lines.append(
            f"  kev: yes  date added: {kev.date_added}  "
            f"ransomware use: {_yes(kev.known_ransomware)}  due: {kev.due_date}"
        )
        lines.append("  required action: " + wrap_untrusted(kev.required_action, "kev"))
    scores = report.epss
    lines.append(
        f"  epss: {_score(scores[0] if scores else None)}"
        f"  percentile: {_score(scores[1] if scores else None)}"
    )
    nvd = report.nvd
    if nvd is not None:
        lines.append(
            f"  published: {nvd.published or 'unknown'}"
            f"  status: {nvd.status or 'unknown'}"
        )
        for score in (nvd.cvss_v40, nvd.cvss_v31):
            if score is not None:
                lines.append(
                    f"  cvss {score.version}: {score.score} {score.severity}"
                    f"  vector: {score.vector}"
                )
        lines.append(f"  cwe: {', '.join(nvd.cwe_ids) or 'none'}")
        lines.append("  description: " + wrap_untrusted(nvd.description, "nvd"))
        for url in nvd.references:
            lines.append("  reference: " + wrap_untrusted(url, "nvd"))
    lines.extend(_notes(report.warnings, ()))
    return "\n".join(lines)


def _render_search(result: AdvisoryResult) -> str:
    lines = _incomplete_lines(result.unavailable)
    rows = result.items[:MAX_ADVISORY_ROWS]
    lines.append(f"{len(result.items)} advisories matched; showing {len(rows)}")
    for advisory in rows:
        packages = ", ".join(f"{a.ecosystem}:{a.name}" for a in advisory.affected)
        lines.append(
            f"- {advisory.ghsa_id}  cve: {advisory.cve_id or 'none'}"
            f"  severity: {advisory.severity or 'unknown'}"
            f"  published: {advisory.published_at or 'unknown'}"
        )
        lines.append(f"  packages: {packages or 'none listed'}")
        if advisory.summary:
            lines.append("  summary: " + wrap_untrusted(advisory.summary, "ghsa"))
        if advisory.url:
            lines.append("  url: " + wrap_untrusted(advisory.url, "ghsa"))
    lines.extend(_notes(result.warnings, ()))
    return "\n".join(lines)


def _incomplete_lines(unavailable: Sequence[str]) -> list[str]:
    if not unavailable:
        return []
    current().services[INCOMPLETE_FLAG] = True
    return [f"{UNAVAILABLE_PREFIX}: {', '.join(unavailable)}"]


def _notes(warnings: Iterable[str], rejected: Iterable[str]) -> list[str]:
    notes = [f"note: {text}" for text in [*warnings, *rejected]]
    return notes


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def _score(value: float | None) -> str:
    return "unknown" if value is None else f"{value:g}"
