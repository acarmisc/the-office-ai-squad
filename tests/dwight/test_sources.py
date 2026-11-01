from __future__ import annotations

import json

import httpx
import pytest
import respx

from code_squad.dwight.deps.model import Package
from code_squad.dwight.intel.epss import EpssClient
from code_squad.dwight.intel.ghsa import GhsaClient
from code_squad.dwight.intel.http import IntelError, IntelHttp
from code_squad.dwight.intel.kev import KEV_URL, KevCatalog
from code_squad.dwight.intel.nvd import NVD_BASE_URL, NvdClient
from tests.dwight.helpers import fixture_json

FAKE_KEY = "fake-token-for-tests"


def _no_sleep(_: float) -> None:
    return None


def test_nvd_maps_cvss_v31_cwe_and_english_description() -> None:
    client = NvdClient(IntelHttp(sleep=_no_sleep))
    with respx.mock(assert_all_mocked=True) as router:
        router.get(NVD_BASE_URL).mock(
            return_value=httpx.Response(
                200, json=fixture_json("nvd_CVE-2021-23337.json")
            )
        )
        cve = client.get_cve("CVE-2021-23337")
    assert cve is not None
    assert cve.cvss_v40 is None
    assert cve.cvss_v31 is not None
    assert cve.cvss_v31.version == "3.1"
    assert cve.cvss_v31.score == 7.2
    assert cve.cvss_v31.severity == "HIGH"
    assert cve.cvss_v31.vector.startswith("CVSS:3.1/")
    assert cve.cwe_ids == ("CWE-77",)
    assert cve.description.startswith("Lodash versions prior to 4.17.21")
    assert cve.references == ("https://nvd.nist.gov/vuln/detail/CVE-2021-23337",)


def test_nvd_maps_cvss_v40_and_skips_non_cwe_weaknesses() -> None:
    client = NvdClient(IntelHttp(sleep=_no_sleep), api_key=FAKE_KEY)
    with respx.mock(assert_all_mocked=True) as router:
        route = router.get(NVD_BASE_URL).mock(
            return_value=httpx.Response(
                200, json=fixture_json("nvd_CVE-2099-0001_v40_synthetic.json")
            )
        )
        cve = client.get_cve("CVE-2099-0001")
        assert route.calls[0].request.headers["apiKey"] == FAKE_KEY
        assert route.calls[0].request.url.params["cveId"] == "CVE-2099-0001"
    assert cve is not None
    assert cve.cvss_v40 is not None
    assert cve.cvss_v40.version == "4.0"
    assert cve.cvss_v40.score == 9.3
    assert cve.cvss_v40.vector.startswith("CVSS:4.0/")
    assert cve.cvss_v31 is not None and cve.cvss_v31.score == 9.8
    assert cve.cwe_ids == ("CWE-20",)


def test_nvd_unknown_cve_returns_none_and_is_not_cached() -> None:
    client = NvdClient(IntelHttp(sleep=_no_sleep))
    empty = {"totalResults": 0, "vulnerabilities": []}
    with respx.mock(assert_all_mocked=True) as router:
        route = router.get(NVD_BASE_URL).mock(
            return_value=httpx.Response(200, json=empty)
        )
        assert client.get_cve("CVE-2099-9999") is None
        assert client.get_cve("CVE-2099-9999") is None
        assert route.call_count == 2


def test_kev_downloads_once_for_many_lookups_and_refreshes_after_ttl() -> None:
    now = [0.0]
    catalog = KevCatalog(
        IntelHttp(sleep=_no_sleep), refresh_seconds=86400, clock=lambda: now[0]
    )
    with respx.mock(assert_all_mocked=True) as router:
        route = router.get(KEV_URL).mock(
            return_value=httpx.Response(200, json=fixture_json("kev_sample.json"))
        )
        assert catalog.is_known_exploited("CVE-2021-44228")
        assert catalog.is_known_exploited("cve-2021-44228")
        assert not catalog.is_known_exploited("CVE-2099-9999")
        entry = catalog.entry("CVE-2021-44228")
        assert entry is not None
        assert entry.date_added == "2021-12-10"
        assert entry.known_ransomware is True
        assert entry.required_action == "Apply updates per vendor instructions."
        assert route.call_count == 1
        now[0] = 86401.0
        assert catalog.is_known_exploited("CVE-2023-0001")
        assert route.call_count == 2


def test_kev_keeps_stale_copy_when_refresh_fails() -> None:
    now = [0.0]
    catalog = KevCatalog(
        IntelHttp(sleep=_no_sleep, max_retries=0),
        refresh_seconds=10,
        clock=lambda: now[0],
    )
    with respx.mock(assert_all_mocked=True) as router:
        router.get(KEV_URL).mock(
            side_effect=[
                httpx.Response(200, json=fixture_json("kev_sample.json")),
                httpx.Response(503),
            ]
        )
        assert catalog.is_known_exploited("CVE-2021-44228")
        now[0] = 11.0
        assert catalog.is_known_exploited("CVE-2021-44228")
        assert catalog.stale is True


def test_kev_without_any_copy_raises_when_download_fails() -> None:
    catalog = KevCatalog(IntelHttp(sleep=_no_sleep, max_retries=0))
    with respx.mock(assert_all_mocked=True) as router:
        router.get(KEV_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(IntelError):
            catalog.is_known_exploited("CVE-2021-44228")


def test_epss_maps_fixture_scores_as_floats() -> None:
    client = EpssClient(IntelHttp(sleep=_no_sleep))
    with respx.mock(assert_all_mocked=True) as router:
        router.get("https://api.first.org/data/v1/epss").mock(
            return_value=httpx.Response(200, json=fixture_json("epss_sample.json"))
        )
        scores = client.scores(["CVE-2021-44228", "CVE-2021-23337"])
    assert scores["CVE-2021-44228"] == pytest.approx((0.97515, 0.99963))
    assert scores["CVE-2021-23337"][0] == pytest.approx(0.00043)


def test_epss_batches_more_than_one_hundred_cves() -> None:
    cves = [f"CVE-2024-{i:04d}" for i in range(150)]

    def handler(request: httpx.Request) -> httpx.Response:
        asked = request.url.params["cve"].split(",")
        assert len(asked) <= 100
        rows = [
            {"cve": c, "epss": "0.5", "percentile": "0.9", "date": "2026-10-30"}
            for c in asked
        ]
        return httpx.Response(200, json={"status": "OK", "data": rows})

    client = EpssClient(IntelHttp(sleep=_no_sleep))
    with respx.mock(assert_all_mocked=True) as router:
        route = router.get("https://api.first.org/data/v1/epss").mock(
            side_effect=handler
        )
        scores = client.scores(cves)
        assert route.call_count == 2
    assert len(scores) == 150
    assert scores["CVE-2024-0149"] == (0.5, 0.9)


def test_ghsa_for_package_maps_ecosystem_and_first_patched() -> None:
    client = GhsaClient(IntelHttp(sleep=_no_sleep), token=FAKE_KEY)
    package = Package("npm", "lodash", "4.17.20", True, "package-lock.json", None, True)
    with respx.mock(assert_all_mocked=True) as router:
        route = router.get("https://api.github.com/advisories").mock(
            return_value=httpx.Response(
                200, json=fixture_json("ghsa_lodash_affects.json")
            )
        )
        advisories = client.for_package("npm", "lodash", "4.17.20")
        params = route.calls[0].request.url.params
        assert params["ecosystem"] == "npm"
        assert params["affects"] == "lodash@4.17.20"
        assert route.calls[0].request.headers["Authorization"] == f"Bearer {FAKE_KEY}"
        assert route.calls[0].request.headers["X-GitHub-Api-Version"]
    assert len(advisories) == 1
    assert advisories[0].cve_id == "CVE-2021-23337"
    assert advisories[0].cwe_ids == ("CWE-77",)
    assert advisories[0].first_patched_for(package) == ("4.17.21",)


def test_ghsa_maps_pypi_to_pip_and_maven_to_maven() -> None:
    client = GhsaClient(IntelHttp(sleep=_no_sleep))
    with respx.mock(assert_all_mocked=True) as router:
        route = router.get("https://api.github.com/advisories").mock(
            return_value=httpx.Response(200, json=[])
        )
        assert client.for_package("PyPI", "requests", "2.31.0") == ()
        assert client.for_package("Maven", "org.x:y", "1.0") == ()
        assert route.calls[0].request.url.params["ecosystem"] == "pip"
        assert route.calls[1].request.url.params["ecosystem"] == "maven"


def test_ghsa_by_cve_rejects_malformed_identifier() -> None:
    client = GhsaClient(IntelHttp(sleep=_no_sleep))
    with pytest.raises(ValueError):
        client.by_cve("not-a-cve")


def test_ghsa_search_filters_by_published_date_and_rejects_bad_dates() -> None:
    client = GhsaClient(IntelHttp(sleep=_no_sleep))
    with respx.mock(assert_all_mocked=True) as router:
        route = router.get("https://api.github.com/advisories").mock(
            return_value=httpx.Response(200, json=json.loads("[]"))
        )
        client.search(ecosystem="npm", since="2026-10-01")
        assert route.calls[0].request.url.params["published"] == ">=2026-10-01"
    with pytest.raises(ValueError):
        client.search(ecosystem=None, since="yesterday")
