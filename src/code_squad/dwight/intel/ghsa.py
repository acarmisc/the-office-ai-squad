from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from code_squad.dwight.deps.model import Package
from code_squad.dwight.intel.cache import TtlCache
from code_squad.dwight.intel.http import IntelHttp, UpstreamError
from code_squad.dwight.intel.ids import is_cve_id, is_iso_date

GITHUB_BASE_URL: Final = "https://api.github.com"
GITHUB_API_VERSION: Final = "2026-03-10"
GHSA_ECOSYSTEMS: Final[Mapping[str, str]] = {
    "npm": "npm",
    "Maven": "maven",
    "PyPI": "pip",
}
PER_PAGE: Final = 100


@dataclass(frozen=True)
class GhsaAffected:
    ecosystem: str
    name: str
    vulnerable_range: str
    first_patched: str | None


@dataclass(frozen=True)
class Advisory:
    ghsa_id: str
    cve_id: str | None
    url: str
    summary: str
    description: str
    severity: str | None
    cwe_ids: tuple[str, ...]
    references: tuple[str, ...]
    published_at: str | None
    affected: tuple[GhsaAffected, ...]

    def first_patched_for(self, package: Package) -> tuple[str, ...]:
        patched = [
            entry.first_patched
            for entry in self.affected
            if entry.name.lower() == package.name.lower() and entry.first_patched
        ]
        return tuple(dict.fromkeys(p for p in patched if p is not None))


class GhsaClient:
    def __init__(
        self,
        http: IntelHttp,
        *,
        token: str | None = None,
        cache: TtlCache[str, tuple[Advisory, ...]] | None = None,
        base_url: str = GITHUB_BASE_URL,
    ) -> None:
        self._http = http
        self._token = token
        self._cache = cache or TtlCache[str, tuple[Advisory, ...]]()
        self._base = base_url.rstrip("/")

    def for_package(
        self, ecosystem: str, name: str, version: str
    ) -> tuple[Advisory, ...]:
        ghsa_ecosystem = GHSA_ECOSYSTEMS.get(ecosystem)
        if ghsa_ecosystem is None:
            return ()
        key = f"pkg|{ghsa_ecosystem}|{name}|{version}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        params = {
            "ecosystem": ghsa_ecosystem,
            "affects": f"{name}@{version}",
            "type": "reviewed",
            "per_page": str(PER_PAGE),
        }
        found = self._fetch(params)
        self._cache.put(key, found)
        return found

    def by_cve(self, cve_id: str) -> tuple[Advisory, ...]:
        if not is_cve_id(cve_id):
            raise ValueError("invalid CVE id")
        key = f"cve|{cve_id}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        found = self._fetch({"cve_id": cve_id, "type": "reviewed"})
        self._cache.put(key, found)
        return found

    def search(
        self, *, ecosystem: str | None, since: str | None
    ) -> tuple[Advisory, ...]:
        params: dict[str, str] = {"type": "reviewed", "per_page": str(PER_PAGE)}
        if ecosystem is not None:
            params["ecosystem"] = ecosystem
        if since is not None:
            if not is_iso_date(since):
                raise ValueError("since must be a YYYY-MM-DD date")
            params["published"] = f">={since}"
        return self._fetch(params)

    def _fetch(self, params: Mapping[str, str]) -> tuple[Advisory, ...]:
        data = self._http.get_json(
            f"{self._base}/advisories", params=params, headers=self._headers()
        )
        if not isinstance(data, list):
            raise UpstreamError("github returned a malformed advisory list")
        return tuple(_parse_advisory(item) for item in data if isinstance(item, dict))

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers


def _parse_advisory(item: Mapping[str, Any]) -> Advisory:
    identifiers = _list(item.get("identifiers"))
    cve = next(
        (
            i.get("value")
            for i in identifiers
            if isinstance(i, dict) and i.get("type") == "CVE"
        ),
        None,
    )
    severity = item.get("severity")
    return Advisory(
        ghsa_id=_str(item.get("ghsa_id")),
        cve_id=cve if isinstance(cve, str) else None,
        url=_str(item.get("html_url")),
        summary=_str(item.get("summary")),
        description=_str(item.get("description")),
        severity=severity if isinstance(severity, str) else None,
        cwe_ids=tuple(
            _str(c.get("cwe_id"))
            for c in _list(item.get("cwes"))
            if isinstance(c, dict)
        ),
        references=tuple(
            r for r in _list(item.get("references")) if isinstance(r, str)
        ),
        published_at=_opt(item.get("published_at")),
        affected=tuple(_affected(v) for v in _list(item.get("vulnerabilities"))),
    )


def _affected(raw: Any) -> GhsaAffected:
    entry = raw if isinstance(raw, dict) else {}
    package = entry.get("package")
    package = package if isinstance(package, dict) else {}
    patched = entry.get("first_patched_version")
    if isinstance(patched, dict):
        patched = patched.get("identifier")
    return GhsaAffected(
        ecosystem=_str(package.get("ecosystem")),
        name=_str(package.get("name")),
        vulnerable_range=_str(entry.get("vulnerable_version_range")),
        first_patched=_opt(patched),
    )


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _opt(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
