from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from code_squad.dwight.intel.http import IntelError, IntelHttp, UpstreamError

KEV_URL: Final = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
DEFAULT_REFRESH_SECONDS: Final = 24 * 3600


@dataclass(frozen=True)
class KevEntry:
    cve_id: str
    vendor: str
    product: str
    name: str
    date_added: str
    short_description: str
    required_action: str
    due_date: str
    known_ransomware: bool


class KevCatalog:
    def __init__(
        self,
        http: IntelHttp,
        *,
        url: str = KEV_URL,
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._url = url
        self._refresh = refresh_seconds
        self._clock = clock
        self._entries: dict[str, KevEntry] = {}
        self._loaded_at: float | None = None
        self._stale = False

    @property
    def stale(self) -> bool:
        return self._stale

    def is_known_exploited(self, cve_id: str) -> bool:
        return self.entry(cve_id) is not None

    def entry(self, cve_id: str) -> KevEntry | None:
        self._ensure_loaded()
        return self._entries.get(cve_id.upper())

    def _ensure_loaded(self) -> None:
        now = self._clock()
        if self._loaded_at is not None and now - self._loaded_at < self._refresh:
            return
        try:
            data = self._http.get_json(self._url)
        except IntelError:
            if self._loaded_at is None:
                raise
            self._stale = True
            self._loaded_at = now
            return
        self._entries = _parse_catalog(data)
        self._loaded_at = now
        self._stale = False


def _parse_catalog(data: Any) -> dict[str, KevEntry]:
    rows = data.get("vulnerabilities") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise UpstreamError("cisa returned a malformed KEV catalog")
    entries: dict[str, KevEntry] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("cveID"), str):
            continue
        entry = KevEntry(
            cve_id=row["cveID"].upper(),
            vendor=_str(row.get("vendorProject")),
            product=_str(row.get("product")),
            name=_str(row.get("vulnerabilityName")),
            date_added=_str(row.get("dateAdded")),
            short_description=_str(row.get("shortDescription")),
            required_action=_str(row.get("requiredAction")),
            due_date=_str(row.get("dueDate")),
            known_ransomware=row.get("knownRansomwareCampaignUse") == "Known",
        )
        entries[entry.cve_id] = entry
    return entries


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""
