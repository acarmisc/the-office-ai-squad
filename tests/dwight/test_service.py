from __future__ import annotations

import httpx
import respx

from code_squad._common.contract import Confidence, Severity
from code_squad.dwight.deps.model import Package
from code_squad.dwight.intel.epss import EPSS_URL, EpssClient
from code_squad.dwight.intel.ghsa import GhsaClient
from code_squad.dwight.intel.http import IntelHttp
from code_squad.dwight.intel.kev import KEV_URL, KevCatalog
from code_squad.dwight.intel.nvd import NVD_BASE_URL, NvdClient
from code_squad.dwight.intel.osv import OsvClient
from code_squad.dwight.intel.service import IntelService
from tests.dwight.helpers import fixture_json

BATCH = "https://api.osv.dev/v1/querybatch"
VULN_35JH = "https://api.osv.dev/v1/vulns/GHSA-35jh-r3h4-6jhm"
VULN_P6MC = "https://api.osv.dev/v1/vulns/GHSA-p6mc-m468-83gw"
GHSA = "https://api.github.com/advisories"
LODASH = Package("npm", "lodash", "4.17.20", True, "package-lock.json", None, True)


def _no_sleep(_: float) -> None:
    return None


def _service(
    *, sources: dict[str, bool] | None = None, max_retries: int = 0
) -> IntelService:
    http = IntelHttp(sleep=_no_sleep, max_retries=max_retries)
    return IntelService(
        osv=OsvClient(http),
        ghsa=GhsaClient(http),
        nvd=NvdClient(http),
        kev=KevCatalog(http),
        epss=EpssClient(http),
        sources_enabled=sources,
    )


def _nvd_handler(request: httpx.Request) -> httpx.Response:
    if request.url.params["cveId"] == "CVE-2021-23337":
        return httpx.Response(200, json=fixture_json("nvd_CVE-2021-23337.json"))
    return httpx.Response(200, json={"totalResults": 0, "vulnerabilities": []})


def _osv_batch() -> dict[str, object]:
    return {
        "results": [
            {
                "vulns": [
                    {"id": "GHSA-35jh-r3h4-6jhm"},
                    {"id": "GHSA-p6mc-m468-83gw"},
                ]
            }
        ]
    }


def test_full_chain_ranks_and_enriches_lodash_findings() -> None:
    service = _service()
    with respx.mock(assert_all_mocked=True) as router:
        router.post(BATCH).mock(return_value=httpx.Response(200, json=_osv_batch()))
        router.get(VULN_35JH).mock(
            return_value=httpx.Response(
                200, json=fixture_json("osv_vuln_GHSA-35jh-r3h4-6jhm.json")
            )
        )
        router.get(VULN_P6MC).mock(
            return_value=httpx.Response(
                200, json=fixture_json("osv_vuln_GHSA-p6mc-m468-83gw.json")
            )
        )
        router.get(GHSA).mock(
            return_value=httpx.Response(
                200, json=fixture_json("ghsa_lodash_affects.json")
            )
        )
        router.get(NVD_BASE_URL).mock(side_effect=_nvd_handler)
        router.get(KEV_URL).mock(
            return_value=httpx.Response(200, json=fixture_json("kev_sample.json"))
        )
        router.get(EPSS_URL).mock(
            return_value=httpx.Response(200, json=fixture_json("epss_sample.json"))
        )
        result = service.lookup_vulnerabilities([LODASH])

    assert result.data_complete is True
    assert result.unavailable == ()
    first, second = result.items
    assert first.vuln_id == "GHSA-35jh-r3h4-6jhm"
    assert first.cve_id == "CVE-2021-23337"
    assert first.cvss == 7.2
    assert first.cvss_source == "nvd-3.1"
    assert first.epss == 0.00043
    assert first.kev is False
    assert first.fixed_versions == ("4.17.21",)
    assert first.cwe_ids == ("CWE-77",)
    assert first.suggested_severity is Severity.MAJOR
    assert first.suggested_confidence is Confidence.MEDIUM
    assert first.verified is True

    assert second.vuln_id == "GHSA-p6mc-m468-83gw"
    assert second.cve_id == "CVE-2020-28500"
    assert second.cvss == 5.3
    assert second.cvss_source == "osv-computed-3.x"
    assert second.epss is None
    assert second.suggested_severity is Severity.MINOR


def test_offline_osv_failure_is_reported_and_results_are_unverified() -> None:
    service = _service()
    with respx.mock(assert_all_mocked=True) as router:
        router.post(BATCH).mock(side_effect=httpx.ConnectError("no route to host"))
        router.get(GHSA).mock(
            return_value=httpx.Response(
                200, json=fixture_json("ghsa_lodash_affects.json")
            )
        )
        router.get(NVD_BASE_URL).mock(side_effect=_nvd_handler)
        router.get(KEV_URL).mock(
            return_value=httpx.Response(200, json=fixture_json("kev_sample.json"))
        )
        router.get(EPSS_URL).mock(
            return_value=httpx.Response(200, json=fixture_json("epss_sample.json"))
        )
        result = service.lookup_vulnerabilities([LODASH])

    assert result.unavailable == ("osv",)
    assert result.data_complete is False
    assert len(result.items) == 1
    item = result.items[0]
    assert item.source == "ghsa"
    assert item.verified is False
    assert item.suggested_confidence is Confidence.LOW


def test_osv_detail_timeouts_are_recorded_and_keep_minimal_matches() -> None:
    service = _service()
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        router.post(BATCH).mock(return_value=httpx.Response(200, json=_osv_batch()))
        router.get(VULN_35JH).mock(side_effect=httpx.ReadTimeout("slow"))
        router.get(VULN_P6MC).mock(side_effect=httpx.ReadTimeout("slow"))
        router.get(GHSA).mock(return_value=httpx.Response(200, json=[]))
        router.get(NVD_BASE_URL).mock(return_value=httpx.Response(503))
        router.get(KEV_URL).mock(
            return_value=httpx.Response(200, json=fixture_json("kev_sample.json"))
        )
        router.get(EPSS_URL).mock(
            return_value=httpx.Response(200, json=fixture_json("epss_sample.json"))
        )
        result = service.lookup_vulnerabilities([LODASH])
    assert result.unavailable == ("osv",)
    assert result.data_complete is False
    assert {item.vuln_id for item in result.items} == {
        "GHSA-35jh-r3h4-6jhm",
        "GHSA-p6mc-m468-83gw",
    }


def test_ghsa_secondary_source_supplies_matches_when_osv_is_empty() -> None:
    service = _service()
    with respx.mock(assert_all_mocked=True) as router:
        router.post(BATCH).mock(
            return_value=httpx.Response(200, json={"results": [{}]})
        )
        router.get(GHSA).mock(
            return_value=httpx.Response(
                200, json=fixture_json("ghsa_lodash_affects.json")
            )
        )
        router.get(NVD_BASE_URL).mock(side_effect=_nvd_handler)
        router.get(KEV_URL).mock(
            return_value=httpx.Response(200, json=fixture_json("kev_sample.json"))
        )
        router.get(EPSS_URL).mock(
            return_value=httpx.Response(200, json=fixture_json("epss_sample.json"))
        )
        result = service.lookup_vulnerabilities([LODASH])
    assert result.unavailable == ()
    assert [item.source for item in result.items] == ["ghsa"]
    assert result.items[0].fixed_versions == ("4.17.21",)


def test_docker_and_unversioned_packages_are_marked_unverified() -> None:
    service = _service()
    docker = Package("Docker", "nginx", "1.27.2", True, "Dockerfile", 4, True)
    unversioned = Package(
        "npm", "bundled", None, False, "package-lock.json", None, None
    )
    with respx.mock(assert_all_mocked=True) as router:
        result = service.lookup_vulnerabilities([docker, unversioned])
        assert len(router.calls) == 0
    assert result.unavailable == ("no-feed:Docker", "unversioned")
    assert result.data_complete is False
    assert result.items == ()


def test_disabled_nvd_is_not_called_and_does_not_mark_data_missing() -> None:
    service = _service(
        sources={"nvd": False, "kev": False, "epss": False, "ghsa": False}
    )
    with respx.mock(assert_all_mocked=True) as router:
        router.post(BATCH).mock(return_value=httpx.Response(200, json=_osv_batch()))
        router.get(VULN_35JH).mock(
            return_value=httpx.Response(
                200, json=fixture_json("osv_vuln_GHSA-35jh-r3h4-6jhm.json")
            )
        )
        router.get(VULN_P6MC).mock(
            return_value=httpx.Response(
                200, json=fixture_json("osv_vuln_GHSA-p6mc-m468-83gw.json")
            )
        )
        result = service.lookup_vulnerabilities([LODASH])
    assert result.data_complete is True
    assert result.items[0].cvss_source == "osv-computed-3.x"
    assert result.items[0].cvss == 7.2


def test_lookup_cve_merges_nvd_kev_and_epss() -> None:
    service = _service()
    with respx.mock(assert_all_mocked=True) as router:
        router.get(NVD_BASE_URL).mock(
            return_value=httpx.Response(
                200, json=fixture_json("nvd_CVE-2099-0001_v40_synthetic.json")
            )
        )
        router.get(KEV_URL).mock(
            return_value=httpx.Response(200, json=fixture_json("kev_sample.json"))
        )
        router.get(EPSS_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        report = service.lookup_cve("CVE-2099-0001")
    assert report.nvd is not None
    assert report.nvd.cvss_v40 is not None and report.nvd.cvss_v40.score == 9.3
    assert report.kev is None
    assert report.epss is None
    assert report.data_complete is True
    report_kev = service.lookup_cve("CVE-2021-44228")
    assert report_kev.kev is not None and report_kev.kev.known_ransomware is True


def test_lookup_cve_reports_nvd_outage() -> None:
    service = _service()
    with respx.mock(assert_all_mocked=True) as router:
        router.get(NVD_BASE_URL).mock(return_value=httpx.Response(503))
        router.get(KEV_URL).mock(
            return_value=httpx.Response(200, json=fixture_json("kev_sample.json"))
        )
        router.get(EPSS_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        report = service.lookup_cve("CVE-2021-23337")
    assert report.unavailable == ("nvd",)
    assert report.data_complete is False


def test_search_advisories_filters_by_keyword_and_passes_ecosystem() -> None:
    service = _service()
    with respx.mock(assert_all_mocked=True) as router:
        route = router.get(GHSA).mock(
            return_value=httpx.Response(
                200, json=fixture_json("ghsa_lodash_affects.json")
            )
        )
        hit = service.search_advisories("lodash", ecosystem="npm", since=None)
        miss = service.search_advisories("django", ecosystem="npm", since=None)
        assert route.calls[0].request.url.params["ecosystem"] == "npm"
    assert len(hit.items) == 1
    assert hit.items[0].ghsa_id == "GHSA-35jh-r3h4-6jhm"
    assert miss.items == ()
