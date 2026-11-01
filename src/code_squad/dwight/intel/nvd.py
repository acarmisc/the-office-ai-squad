from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from code_squad.dwight.intel.cache import TtlCache
from code_squad.dwight.intel.http import IntelHttp
from code_squad.dwight.intel.ids import is_cve_id

NVD_BASE_URL: Final = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_CWE: Final = re.compile(r"^CWE-\d+$")
_METRIC_VERSIONS: Final[Mapping[str, str]] = {
    "cvssMetricV31": "3.1",
    "cvssMetricV40": "4.0",
}


@dataclass(frozen=True)
class CvssScore:
    version: str
    score: float
    severity: str
    vector: str


@dataclass(frozen=True)
class NvdCve:
    id: str
    description: str
    published: str | None
    status: str | None
    cvss_v31: CvssScore | None
    cvss_v40: CvssScore | None
    cwe_ids: tuple[str, ...]
    references: tuple[str, ...]


class NvdClient:
    def __init__(
        self,
        http: IntelHttp,
        *,
        api_key: str | None = None,
        cache: TtlCache[str, NvdCve] | None = None,
        base_url: str = NVD_BASE_URL,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self._cache = cache or TtlCache[str, NvdCve]()
        self._base = base_url

    def get_cve(self, cve_id: str) -> NvdCve | None:
        if not is_cve_id(cve_id):
            raise ValueError("invalid CVE id")
        cached = self._cache.get(cve_id)
        if cached is not None:
            return cached
        headers = {"apiKey": self._api_key} if self._api_key else None
        data = self._http.get_json(
            self._base, params={"cveId": cve_id}, headers=headers
        )
        cve = _first_cve(data)
        if cve is None:
            return None
        parsed = _parse_cve(cve)
        self._cache.put(cve_id, parsed)
        return parsed


def _first_cve(data: Any) -> Mapping[str, Any] | None:
    if not isinstance(data, dict):
        return None
    vulns = data.get("vulnerabilities")
    if not isinstance(vulns, list) or not vulns:
        return None
    first = vulns[0]
    cve = first.get("cve") if isinstance(first, dict) else None
    return cve if isinstance(cve, dict) else None


def _parse_cve(cve: Mapping[str, Any]) -> NvdCve:
    metrics = cve.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    return NvdCve(
        id=_str(cve.get("id")),
        description=_english(cve.get("descriptions")),
        published=_opt(cve.get("published")),
        status=_opt(cve.get("vulnStatus")),
        cvss_v31=_metric(metrics, "cvssMetricV31"),
        cvss_v40=_metric(metrics, "cvssMetricV40"),
        cwe_ids=_cwes(cve.get("weaknesses")),
        references=tuple(
            _str(ref.get("url"))
            for ref in _list(cve.get("references"))
            if isinstance(ref, dict) and isinstance(ref.get("url"), str)
        ),
    )


def _metric(metrics: Mapping[str, Any], key: str) -> CvssScore | None:
    entries = [e for e in _list(metrics.get(key)) if isinstance(e, dict)]
    if not entries:
        return None
    chosen = next((e for e in entries if e.get("type") == "Primary"), entries[0])
    data = chosen.get("cvssData")
    if not isinstance(data, dict):
        return None
    score = data.get("baseScore")
    vector = data.get("vectorString")
    severity = data.get("baseSeverity")
    if not isinstance(score, int | float) or not isinstance(vector, str):
        return None
    return CvssScore(
        version=_METRIC_VERSIONS[key],
        score=float(score),
        severity=_str(severity),
        vector=vector,
    )


def _cwes(raw: Any) -> tuple[str, ...]:
    found: list[str] = []
    for weakness in _list(raw):
        if not isinstance(weakness, dict):
            continue
        for item in _list(weakness.get("description")):
            value = item.get("value") if isinstance(item, dict) else None
            if isinstance(value, str) and _CWE.match(value):
                found.append(value)
    return tuple(dict.fromkeys(found))


def _english(raw: Any) -> str:
    for item in _list(raw):
        if isinstance(item, dict) and item.get("lang") == "en":
            return _str(item.get("value"))
    return ""


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _opt(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
