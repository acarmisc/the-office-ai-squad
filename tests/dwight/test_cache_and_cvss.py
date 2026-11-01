from __future__ import annotations

from code_squad._common.observability import REGISTRY
from code_squad.dwight.intel.cache import TtlCache
from code_squad.dwight.intel.cvss import cvss3_base_score, severity_band


def _hits() -> float:
    return REGISTRY.get_sample_value("squad_cve_cache_hits_total") or 0.0


def test_cache_hit_increments_metric_and_expiry_is_respected() -> None:
    now = [0.0]
    cache: TtlCache[str, int] = TtlCache(ttl_seconds=10, clock=lambda: now[0])
    cache.put("a", 1)
    before = _hits()
    assert cache.get("a") == 1
    assert cache.get("a") == 1
    assert _hits() - before == 2
    assert cache.get("missing") is None
    now[0] = 10.0
    assert cache.get("a") is None
    assert _hits() - before == 2


def test_cache_evicts_oldest_entries_beyond_limit() -> None:
    cache: TtlCache[str, int] = TtlCache(max_entries=2, clock=lambda: 0.0)
    for index, key in enumerate(["a", "b", "c"]):
        cache.put(key, index)
    assert len(cache) == 2
    assert cache.get("a") is None


def test_cvss_v31_base_scores_match_reference_vectors() -> None:
    assert cvss3_base_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == 9.8
    assert cvss3_base_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N") == 6.1
    assert cvss3_base_score("CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:U/C:H/I:H/A:H") == 7.2
    assert cvss3_base_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N") == 0.0


def test_cvss_rejects_malformed_or_v4_vectors() -> None:
    assert cvss3_base_score("CVSS:3.1/AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") is None
    assert (
        cvss3_base_score(
            "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"
        )
        is None
    )
    assert cvss3_base_score("garbage") is None


def test_severity_bands() -> None:
    assert severity_band(9.8) == "CRITICAL"
    assert severity_band(7.2) == "HIGH"
    assert severity_band(5.3) == "MEDIUM"
    assert severity_band(2.0) == "LOW"
