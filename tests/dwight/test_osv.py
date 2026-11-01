from __future__ import annotations

import json

import httpx
import pytest
import respx

from code_squad._common.observability import REGISTRY
from code_squad.dwight.deps.model import Package
from code_squad.dwight.intel.cache import TtlCache
from code_squad.dwight.intel.http import IntelHttp, UpstreamError
from code_squad.dwight.intel.osv import OsvClient, Vuln
from tests.dwight.helpers import fixture_json

BATCH = "https://api.osv.dev/v1/querybatch"
VULN = "https://api.osv.dev/v1/vulns/GHSA-35jh-r3h4-6jhm"


def _pkg(name: str, version: str | None, ecosystem: str = "npm") -> Package:
    return Package(
        ecosystem=ecosystem,  # type: ignore[arg-type]
        name=name,
        version=version,
        pinned=version is not None,
        source_file="package-lock.json",
        line=None,
        direct=True,
    )


def _no_sleep(_: float) -> None:
    return None


def _batch_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if any("page_token" in q for q in body["queries"]):
        return httpx.Response(200, json=fixture_json("osv_querybatch_page2.json"))
    return httpx.Response(200, json=fixture_json("osv_querybatch_page1.json"))


def test_query_batch_follows_next_page_tokens_and_maps_results() -> None:
    packages = [
        _pkg("lodash", "4.17.20"),
        _pkg("express", "4.17.1"),
        _pkg("accepts", "1.3.7"),
    ]
    client = OsvClient(IntelHttp(sleep=_no_sleep))
    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(BATCH).mock(side_effect=_batch_handler)
        found = client.query_batch(packages)
        assert route.call_count == 2
        first = json.loads(route.calls[0].request.content)
        assert first["queries"][0] == {
            "package": {"name": "lodash", "ecosystem": "npm"},
            "version": "4.17.20",
        }
        second = json.loads(route.calls[1].request.content)
        assert second["queries"][0]["page_token"] == "page-2-token"
    assert found[packages[0]] == ("GHSA-35jh-r3h4-6jhm", "GHSA-p6mc-m468-83gw")
    assert found[packages[1]] == ("GHSA-2qrg-x229-3v8q",)
    assert found[packages[2]] == ()


def test_packages_without_version_or_feed_are_not_sent() -> None:
    client = OsvClient(IntelHttp(sleep=_no_sleep))
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        route = router.post(BATCH).mock(
            return_value=httpx.Response(200, json={"results": [{}]})
        )
        found = client.query_batch(
            [_pkg("lodash", None), _pkg("ubuntu", "1", ecosystem="Docker")]
        )
        assert found == {}
        assert route.call_count == 0


def test_query_results_are_cached_and_hits_are_counted() -> None:
    packages = [
        _pkg("lodash", "4.17.20"),
        _pkg("express", "4.17.1"),
        _pkg("accepts", "1.3.7"),
    ]
    client = OsvClient(IntelHttp(sleep=_no_sleep))
    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(BATCH).mock(side_effect=_batch_handler)
        client.query_batch(packages)
        calls = route.call_count
        before = REGISTRY.get_sample_value("squad_cve_cache_hits_total") or 0.0
        again = client.query_batch(packages)
        assert route.call_count == calls
    assert len(again) == 3
    after = REGISTRY.get_sample_value("squad_cve_cache_hits_total") or 0.0
    assert after - before == 3


def test_malformed_batch_response_is_an_upstream_error() -> None:
    client = OsvClient(IntelHttp(sleep=_no_sleep))
    with respx.mock(assert_all_mocked=True) as router:
        router.post(BATCH).mock(return_value=httpx.Response(200, json={"results": []}))
        with pytest.raises(UpstreamError):
            client.query_batch([_pkg("lodash", "4.17.20")])


def test_get_vuln_maps_detail_record_and_fixed_versions() -> None:
    client = OsvClient(IntelHttp(sleep=_no_sleep))
    package = _pkg("lodash", "4.17.20")
    with respx.mock(assert_all_mocked=True) as router:
        router.get(VULN).mock(
            return_value=httpx.Response(
                200, json=fixture_json("osv_vuln_GHSA-35jh-r3h4-6jhm.json")
            )
        )
        vuln: Vuln = client.get_vuln("GHSA-35jh-r3h4-6jhm")
    assert vuln.aliases == ("CVE-2021-23337",)
    assert vuln.cve_ids() == ("CVE-2021-23337",)
    assert vuln.severities[0].kind == "CVSS_V3"
    assert vuln.severities[0].vector.startswith("CVSS:3.1/")
    assert vuln.database_severity == "HIGH"
    assert vuln.fixed_versions(package) == ("4.17.21",)
    assert vuln.fixed_versions(_pkg("lodash", "4.17.21")) == ("4.17.21",)
    assert len(vuln.references) == 2
    assert "Command Injection" in vuln.summary


def test_get_vuln_rejects_ids_that_could_change_the_path() -> None:
    client = OsvClient(IntelHttp(sleep=_no_sleep))
    with respx.mock(assert_all_mocked=True) as router:
        with pytest.raises(ValueError):
            client.get_vuln("../v1/query")
        assert len(router.calls) == 0


def test_vuln_cache_avoids_second_detail_request() -> None:
    client = OsvClient(IntelHttp(sleep=_no_sleep), vuln_cache=TtlCache[str, Vuln]())
    with respx.mock(assert_all_mocked=True) as router:
        route = router.get(VULN).mock(
            return_value=httpx.Response(
                200, json=fixture_json("osv_vuln_GHSA-35jh-r3h4-6jhm.json")
            )
        )
        client.get_vuln("GHSA-35jh-r3h4-6jhm")
        client.get_vuln("GHSA-35jh-r3h4-6jhm")
        assert route.call_count == 1
