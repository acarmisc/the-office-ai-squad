from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Final, TypeVar

from code_squad._common.contract import Confidence, Severity
from code_squad.dwight.deps.model import Package
from code_squad.dwight.intel.cvss import cvss3_base_score
from code_squad.dwight.intel.epss import EpssClient
from code_squad.dwight.intel.ghsa import GHSA_ECOSYSTEMS, Advisory, GhsaClient
from code_squad.dwight.intel.http import IntelError
from code_squad.dwight.intel.kev import KevCatalog, KevEntry
from code_squad.dwight.intel.nvd import NvdClient, NvdCve
from code_squad.dwight.intel.osv import OSV_ECOSYSTEMS, OsvClient, Vuln
from code_squad.dwight.intel.triage import (
    RankKey,
    SeverityThresholds,
    rank_key,
    suggested_confidence,
    suggested_severity,
)

SOURCE_NAMES: Final = ("osv", "ghsa", "nvd", "kev", "epss")
MAX_REFERENCES: Final = 20
MAX_SUMMARY_CHARS: Final = 1000
UNVERSIONED: Final = "unversioned"
NO_FEED_DOCKER: Final = "no-feed:Docker"
_T = TypeVar("_T")


@dataclass(frozen=True)
class VulnMatch:
    package: Package
    vuln_id: str
    source: str
    aliases: tuple[str, ...]
    cve_id: str | None
    summary: str
    references: tuple[str, ...]
    fixed_versions: tuple[str, ...]
    cwe_ids: tuple[str, ...]
    cvss: float | None
    cvss_source: str | None
    cvss_vector: str | None
    epss: float | None
    epss_percentile: float | None
    kev: bool
    rank_key: RankKey
    suggested_severity: Severity
    suggested_confidence: Confidence
    verified: bool


@dataclass(frozen=True)
class LookupResult:
    items: tuple[VulnMatch, ...]
    unavailable: tuple[str, ...]
    warnings: tuple[str, ...]
    data_complete: bool


@dataclass(frozen=True)
class CveReport:
    cve_id: str
    nvd: NvdCve | None
    kev: KevEntry | None
    epss: tuple[float, float] | None
    unavailable: tuple[str, ...]
    warnings: tuple[str, ...]
    data_complete: bool


@dataclass(frozen=True)
class AdvisoryResult:
    items: tuple[Advisory, ...]
    unavailable: tuple[str, ...]
    warnings: tuple[str, ...]
    data_complete: bool


@dataclass(frozen=True)
class _Draft:
    package: Package
    vuln_id: str
    source: str
    aliases: tuple[str, ...]
    cve_id: str | None
    summary: str
    references: tuple[str, ...]
    fixed_versions: tuple[str, ...]
    cwe_ids: tuple[str, ...]
    osv_cvss: float | None
    osv_vector: str | None


@dataclass
class _Run:
    failed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, source: str) -> None:
        if source not in self.failed:
            self.failed.append(source)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


class IntelService:
    def __init__(
        self,
        *,
        osv: OsvClient,
        ghsa: GhsaClient,
        nvd: NvdClient,
        kev: KevCatalog,
        epss: EpssClient,
        sources_enabled: Mapping[str, bool] | None = None,
        thresholds: SeverityThresholds | None = None,
    ) -> None:
        self._osv = osv
        self._ghsa = ghsa
        self._nvd = nvd
        self._kev = kev
        self._epss = epss
        self._enabled = {name: True for name in SOURCE_NAMES}
        self._enabled.update(sources_enabled or {})
        self._thresholds = thresholds or SeverityThresholds()

    def lookup_vulnerabilities(self, packages: Sequence[Package]) -> LookupResult:
        run = _Run()
        targets = self._targets(packages, run)
        osv_drafts = self._osv_drafts(targets, run)
        drafts = osv_drafts + self._ghsa_drafts(targets, osv_drafts, run)
        matches = self._finish_all(drafts, run)
        return LookupResult(
            items=tuple(matches),
            unavailable=tuple(run.failed),
            warnings=tuple(run.warnings),
            data_complete=not run.failed,
        )

    def lookup_cve(self, cve_id: str) -> CveReport:
        run = _Run()
        nvd = self._attempt(run, "nvd", lambda: self._nvd.get_cve(cve_id))
        kev = self._attempt(run, "kev", lambda: self._kev.entry(cve_id))
        scores = self._attempt(run, "epss", lambda: self._epss.scores([cve_id]))
        if self._enabled["kev"] and self._kev.stale:
            run.warn("KEV catalog could not be refreshed; using the cached copy")
        if nvd is None and "nvd" not in run.failed and self._enabled["nvd"]:
            run.warn("CVE not found in NVD")
        return CveReport(
            cve_id=cve_id,
            nvd=nvd,
            kev=kev,
            epss=scores.get(cve_id) if scores else None,
            unavailable=tuple(run.failed),
            warnings=tuple(run.warnings),
            data_complete=not run.failed,
        )

    def search_advisories(
        self, query: str, *, ecosystem: str | None, since: str | None
    ) -> AdvisoryResult:
        run = _Run()
        ghsa_ecosystem = GHSA_ECOSYSTEMS.get(ecosystem) if ecosystem else None
        advisories = self._attempt(
            run,
            "ghsa",
            lambda: self._ghsa.search(ecosystem=ghsa_ecosystem, since=since),
        )
        needle = query.strip().lower()
        items = tuple(
            a for a in (advisories or ()) if not needle or needle in _haystack(a)
        )
        return AdvisoryResult(
            items=items,
            unavailable=tuple(run.failed),
            warnings=tuple(run.warnings),
            data_complete=not run.failed,
        )

    def _on(self, source: str) -> bool:
        return self._enabled.get(source, False)

    def _attempt(self, run: _Run, source: str, call: Callable[[], _T]) -> _T | None:
        if source in run.failed or not self._on(source):
            return None
        try:
            return call()
        except IntelError:
            run.fail(source)
            return None

    def _targets(self, packages: Sequence[Package], run: _Run) -> list[Package]:
        targets: list[Package] = []
        for package in packages:
            if package.ecosystem not in OSV_ECOSYSTEMS:
                run.fail(NO_FEED_DOCKER)
                run.warn(
                    f"{package.source_file}: no vulnerability feed for {package.name}"
                )
            elif package.version is None:
                run.fail(UNVERSIONED)
                run.warn(
                    f"{package.source_file}: {package.name} has no resolved version"
                )
            else:
                targets.append(package)
        return targets

    def _osv_drafts(self, targets: Sequence[Package], run: _Run) -> list[_Draft]:
        if not targets:
            return []
        if not self._on("osv"):
            run.fail("osv")
            return []
        found = self._attempt(run, "osv", lambda: self._osv.query_batch(targets))
        drafts: list[_Draft] = []
        for package, ids in (found or {}).items():
            for vuln_id in ids:
                vuln = self._load_vuln(run, vuln_id)
                drafts.append(_osv_draft(package, vuln_id, vuln))
        return drafts

    def _load_vuln(self, run: _Run, vuln_id: str) -> Vuln | None:
        if not self._on("osv"):
            return None
        return self._attempt(run, "osv", lambda: self._osv.get_vuln(vuln_id))

    def _ghsa_drafts(
        self, targets: Sequence[Package], osv_drafts: Sequence[_Draft], run: _Run
    ) -> list[_Draft]:
        drafts: list[_Draft] = []
        for package in targets:
            advisories = self._attempt(
                run,
                "ghsa",
                partial(
                    self._ghsa.for_package,
                    package.ecosystem,
                    package.name,
                    package.version or "",
                ),
            )
            known = _known_ids(package, [*osv_drafts, *drafts])
            for advisory in advisories or ():
                if advisory.ghsa_id in known or advisory.cve_id in known:
                    continue
                drafts.append(_ghsa_draft(package, advisory))
                known.add(advisory.ghsa_id)
        return drafts

    def _finish_all(self, drafts: Sequence[_Draft], run: _Run) -> list[VulnMatch]:
        cves = sorted({d.cve_id for d in drafts if d.cve_id})
        nvd: dict[str, NvdCve] = {}
        for cve in cves:
            record = self._attempt(run, "nvd", partial(self._nvd.get_cve, cve))
            if record is not None:
                nvd[cve] = record
        kev = self._attempt(
            run,
            "kev",
            lambda: {cve: self._kev.is_known_exploited(cve) for cve in cves},
        )
        epss = self._attempt(run, "epss", lambda: self._epss.scores(cves))
        verified = not run.failed
        matches = [
            self._finish(d, nvd, kev or {}, epss or {}, verified) for d in drafts
        ]
        matches.sort(
            key=lambda m: (m.rank_key, m.package.name, m.vuln_id), reverse=True
        )
        return matches

    def _finish(
        self,
        draft: _Draft,
        nvd: Mapping[str, NvdCve],
        kev: Mapping[str, bool],
        epss: Mapping[str, tuple[float, float]],
        verified: bool,
    ) -> VulnMatch:
        record = nvd.get(draft.cve_id) if draft.cve_id else None
        cvss, cvss_source, vector = _select_cvss(record, draft)
        is_kev = bool(draft.cve_id and kev.get(draft.cve_id))
        scores = epss.get(draft.cve_id) if draft.cve_id else None
        epss_score = scores[0] if scores else None
        key = rank_key(kev=is_kev, epss=epss_score, cvss=cvss)
        severity = suggested_severity(
            kev=is_kev, epss=epss_score, cvss=cvss, thresholds=self._thresholds
        )
        references = _merge(draft.references, record.references if record else ())
        return VulnMatch(
            package=draft.package,
            vuln_id=draft.vuln_id,
            source=draft.source,
            aliases=draft.aliases,
            cve_id=draft.cve_id,
            summary=draft.summary,
            references=references,
            fixed_versions=draft.fixed_versions,
            cwe_ids=draft.cwe_ids or (record.cwe_ids if record else ()),
            cvss=cvss,
            cvss_source=cvss_source,
            cvss_vector=vector,
            epss=epss_score,
            epss_percentile=scores[1] if scores else None,
            kev=is_kev,
            rank_key=key,
            suggested_severity=severity,
            suggested_confidence=suggested_confidence(verified=verified),
            verified=verified,
        )


def _osv_draft(package: Package, vuln_id: str, vuln: Vuln | None) -> _Draft:
    if vuln is None:
        cve = vuln_id if vuln_id.startswith("CVE-") else None
        return _Draft(package, vuln_id, "osv", (), cve, "", (), (), (), None, None)
    osv_cvss, osv_vector = _osv_v3(vuln)
    summary = vuln.summary or vuln.details[:MAX_SUMMARY_CHARS]
    return _Draft(
        package=package,
        vuln_id=vuln.id,
        source="osv",
        aliases=vuln.aliases,
        cve_id=next(iter(vuln.cve_ids()), None),
        summary=summary,
        references=tuple(r.url for r in vuln.references if r.url),
        fixed_versions=vuln.fixed_versions(package),
        cwe_ids=(),
        osv_cvss=osv_cvss,
        osv_vector=osv_vector,
    )


def _osv_v3(vuln: Vuln) -> tuple[float | None, str | None]:
    for severity in vuln.severities:
        if severity.kind.startswith("CVSS_V3"):
            return cvss3_base_score(severity.vector), severity.vector
    return None, None


def _ghsa_draft(package: Package, advisory: Advisory) -> _Draft:
    aliases = (advisory.cve_id,) if advisory.cve_id else ()
    return _Draft(
        package=package,
        vuln_id=advisory.ghsa_id,
        source="ghsa",
        aliases=aliases,
        cve_id=advisory.cve_id,
        summary=advisory.summary or advisory.description[:MAX_SUMMARY_CHARS],
        references=_merge((advisory.url,), advisory.references),
        fixed_versions=advisory.first_patched_for(package),
        cwe_ids=advisory.cwe_ids,
        osv_cvss=None,
        osv_vector=None,
    )


def _select_cvss(
    record: NvdCve | None, draft: _Draft
) -> tuple[float | None, str | None, str | None]:
    if record is not None and record.cvss_v40 is not None:
        return record.cvss_v40.score, "nvd-4.0", record.cvss_v40.vector
    if record is not None and record.cvss_v31 is not None:
        return record.cvss_v31.score, "nvd-3.1", record.cvss_v31.vector
    if draft.osv_cvss is not None:
        return draft.osv_cvss, "osv-computed-3.x", draft.osv_vector
    return None, None, None


def _known_ids(package: Package, drafts: Sequence[_Draft]) -> set[str]:
    known: set[str] = set()
    for draft in drafts:
        if draft.package == package:
            known.update(filter(None, (draft.vuln_id, draft.cve_id, *draft.aliases)))
    return known


def _merge(first: Sequence[str], second: Sequence[str]) -> tuple[str, ...]:
    combined = [url for url in (*first, *second) if url]
    return tuple(dict.fromkeys(combined))[:MAX_REFERENCES]


def _haystack(advisory: Advisory) -> str:
    names = " ".join(entry.name for entry in advisory.affected)
    parts = (advisory.ghsa_id, advisory.cve_id or "", advisory.summary, names)
    return " ".join(parts).lower()
