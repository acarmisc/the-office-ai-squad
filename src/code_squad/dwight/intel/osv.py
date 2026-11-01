from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from code_squad.dwight.deps.model import Package
from code_squad.dwight.intel.cache import TtlCache
from code_squad.dwight.intel.http import IntelHttp, UpstreamError
from code_squad.dwight.intel.ids import is_vuln_id

OSV_BASE_URL: Final = "https://api.osv.dev"
OSV_ECOSYSTEMS: Final[Mapping[str, str]] = {
    "npm": "npm",
    "Maven": "Maven",
    "PyPI": "PyPI",
}
MAX_QUERIES_PER_BATCH: Final = 1000
MAX_PAGES: Final = 20


@dataclass(frozen=True)
class OsvReference:
    kind: str
    url: str


@dataclass(frozen=True)
class OsvSeverity:
    kind: str
    vector: str


@dataclass(frozen=True)
class OsvAffected:
    ecosystem: str
    package_name: str
    fixed: tuple[str, ...]


@dataclass(frozen=True)
class Vuln:
    id: str
    summary: str
    details: str
    aliases: tuple[str, ...]
    published: str | None
    modified: str | None
    withdrawn: bool
    severities: tuple[OsvSeverity, ...]
    affected: tuple[OsvAffected, ...]
    references: tuple[OsvReference, ...]
    database_severity: str | None

    def fixed_versions(self, package: Package) -> tuple[str, ...]:
        fixed: list[str] = []
        for entry in self.affected:
            if entry.ecosystem == package.ecosystem and (
                entry.package_name.lower() == package.name.lower()
            ):
                fixed.extend(entry.fixed)
        return tuple(dict.fromkeys(fixed))

    def cve_ids(self) -> tuple[str, ...]:
        candidates = (self.id, *self.aliases)
        return tuple(dict.fromkeys(c for c in candidates if c.startswith("CVE-")))


class OsvClient:
    def __init__(
        self,
        http: IntelHttp,
        *,
        query_cache: TtlCache[str, tuple[str, ...]] | None = None,
        vuln_cache: TtlCache[str, Vuln] | None = None,
        base_url: str = OSV_BASE_URL,
    ) -> None:
        self._http = http
        self._queries = query_cache or TtlCache[str, tuple[str, ...]]()
        self._vulns = vuln_cache or TtlCache[str, Vuln]()
        self._base = base_url.rstrip("/")

    def query_batch(
        self, packages: Sequence[Package]
    ) -> dict[Package, tuple[str, ...]]:
        results: dict[Package, tuple[str, ...]] = {}
        pending: list[Package] = []
        for package in _queryable(packages):
            cached = self._queries.get(_key(package))
            if cached is None:
                pending.append(package)
            else:
                results[package] = cached
        for start in range(0, len(pending), MAX_QUERIES_PER_BATCH):
            chunk = pending[start : start + MAX_QUERIES_PER_BATCH]
            results.update(self._query_chunk(chunk))
        return results

    def get_vuln(self, vuln_id: str) -> Vuln:
        if not is_vuln_id(vuln_id):
            raise ValueError("invalid vulnerability id")
        cached = self._vulns.get(vuln_id)
        if cached is not None:
            return cached
        data = self._http.get_json(f"{self._base}/v1/vulns/{vuln_id}")
        vuln = _parse_vuln(data)
        self._vulns.put(vuln_id, vuln)
        return vuln

    def _query_chunk(self, chunk: list[Package]) -> dict[Package, tuple[str, ...]]:
        body = {"queries": [_query(package) for package in chunk]}
        rows = self._rows(self._http.post_json(f"{self._base}/v1/querybatch", body))
        if len(rows) != len(chunk):
            raise UpstreamError("osv returned a malformed querybatch result")
        out: dict[Package, tuple[str, ...]] = {}
        for package, row in zip(chunk, rows, strict=True):
            ids = list(_ids(row))
            token = _token(row)
            pages = 1
            while token is not None:
                if pages >= MAX_PAGES:
                    raise UpstreamError("osv pagination exceeded the page limit")
                page = self._query_one(package, token)
                ids.extend(_ids(page))
                token = _token(page)
                pages += 1
            found = tuple(sorted(set(ids)))
            out[package] = found
            self._queries.put(_key(package), found)
        return out

    def _query_one(self, package: Package, token: str) -> Mapping[str, Any]:
        body = {"queries": [_query(package, page_token=token)]}
        rows = self._rows(self._http.post_json(f"{self._base}/v1/querybatch", body))
        if len(rows) != 1:
            raise UpstreamError("osv returned a malformed page result")
        return rows[0]

    @staticmethod
    def _rows(data: Any) -> list[Mapping[str, Any]]:
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise UpstreamError("osv returned no results list")
        return [row if isinstance(row, dict) else {} for row in results]


def _queryable(packages: Sequence[Package]) -> Iterator[Package]:
    seen: set[str] = set()
    for package in packages:
        if package.version is None or package.ecosystem not in OSV_ECOSYSTEMS:
            continue
        key = _key(package)
        if key not in seen:
            seen.add(key)
            yield package


def _key(package: Package) -> str:
    return f"{package.ecosystem}|{package.name}|{package.version}"


def _query(package: Package, page_token: str | None = None) -> dict[str, Any]:
    query: dict[str, Any] = {
        "package": {
            "name": package.name,
            "ecosystem": OSV_ECOSYSTEMS[package.ecosystem],
        },
        "version": package.version,
    }
    if page_token is not None:
        query["page_token"] = page_token
    return query


def _ids(row: Mapping[str, Any]) -> Iterator[str]:
    vulns = row.get("vulns")
    if not isinstance(vulns, list):
        return
    for vuln in vulns:
        if isinstance(vuln, dict) and isinstance(vuln.get("id"), str):
            yield vuln["id"]


def _token(row: Mapping[str, Any]) -> str | None:
    token = row.get("next_page_token")
    return token if isinstance(token, str) and token else None


def _parse_vuln(data: Any) -> Vuln:
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        raise UpstreamError("osv returned a malformed vulnerability record")
    database = data.get("database_specific")
    severity = database.get("severity") if isinstance(database, dict) else None
    return Vuln(
        id=data["id"],
        summary=_str(data.get("summary")),
        details=_str(data.get("details")),
        aliases=tuple(a for a in _list(data.get("aliases")) if isinstance(a, str)),
        published=_opt(data.get("published")),
        modified=_opt(data.get("modified")),
        withdrawn=isinstance(data.get("withdrawn"), str),
        severities=tuple(_severity(s) for s in _list(data.get("severity"))),
        affected=tuple(_affected(a) for a in _list(data.get("affected"))),
        references=tuple(_reference(r) for r in _list(data.get("references"))),
        database_severity=severity if isinstance(severity, str) else None,
    )


def _severity(raw: Any) -> OsvSeverity:
    entry = raw if isinstance(raw, dict) else {}
    return OsvSeverity(_str(entry.get("type")), _str(entry.get("score")))


def _affected(raw: Any) -> OsvAffected:
    entry = raw if isinstance(raw, dict) else {}
    package = entry.get("package")
    package = package if isinstance(package, dict) else {}
    fixed: list[str] = []
    for item in _list(entry.get("ranges")):
        if not isinstance(item, dict):
            continue
        for event in _list(item.get("events")):
            if isinstance(event, dict) and isinstance(event.get("fixed"), str):
                fixed.append(event["fixed"])
    return OsvAffected(
        ecosystem=_str(package.get("ecosystem")),
        package_name=_str(package.get("name")),
        fixed=tuple(dict.fromkeys(fixed)),
    )


def _reference(raw: Any) -> OsvReference:
    entry = raw if isinstance(raw, dict) else {}
    return OsvReference(_str(entry.get("type")), _str(entry.get("url")))


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _opt(value: Any) -> str | None:
    return value if isinstance(value, str) else None
