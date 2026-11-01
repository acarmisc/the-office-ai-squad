from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, Final

from code_squad.dwight.intel.cache import TtlCache
from code_squad.dwight.intel.http import IntelHttp
from code_squad.dwight.intel.ids import is_cve_id

EPSS_URL: Final = "https://api.first.org/data/v1/epss"
EPSS_BATCH_SIZE: Final = 100


class EpssClient:
    def __init__(
        self,
        http: IntelHttp,
        *,
        cache: TtlCache[str, tuple[float, float]] | None = None,
        base_url: str = EPSS_URL,
        batch_size: int = EPSS_BATCH_SIZE,
    ) -> None:
        self._http = http
        self._cache = cache or TtlCache[str, tuple[float, float]]()
        self._base = base_url
        self._batch = batch_size

    def scores(self, cves: Sequence[str]) -> dict[str, tuple[float, float]]:
        wanted = [c for c in dict.fromkeys(c.upper() for c in cves) if is_cve_id(c)]
        found: dict[str, tuple[float, float]] = {}
        pending: list[str] = []
        for cve in wanted:
            cached = self._cache.get(cve)
            if cached is None:
                pending.append(cve)
            else:
                found[cve] = cached
        for chunk in _batches(pending, self._batch):
            data = self._http.get_json(self._base, params={"cve": ",".join(chunk)})
            for cve, score in _rows(data):
                found[cve] = score
                self._cache.put(cve, score)
        return found


def _batches(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _rows(data: Any) -> Iterator[tuple[str, tuple[float, float]]]:
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        cve = row.get("cve")
        epss = _number(row.get("epss"))
        percentile = _number(row.get("percentile"))
        if isinstance(cve, str) and epss is not None and percentile is not None:
            yield cve.upper(), (epss, percentile)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
