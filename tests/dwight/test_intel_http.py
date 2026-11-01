from __future__ import annotations

import httpx
import pytest
import respx

from code_squad.dwight.intel.http import (
    HostNotAllowedError,
    IntelHttp,
    UpstreamError,
)

API = "https://api.osv.dev/v1/vulns/GHSA-test"


def _no_sleep(_: float) -> None:
    return None


def test_non_allow_listed_host_raises_before_any_request() -> None:
    http = IntelHttp(sleep=_no_sleep)
    with respx.mock(assert_all_mocked=True) as router:
        with pytest.raises(HostNotAllowedError):
            http.get_json("https://evil.example/exfil")
        assert len(router.calls) == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://api.osv.dev@evil.example/x",
        "http://api.osv.dev/v1/vulns/x",
        "https://api.osv.dev.evil.example/x",
        "file:///etc/passwd",
    ],
)
def test_host_tricks_and_plain_http_are_refused(url: str) -> None:
    http = IntelHttp(sleep=_no_sleep)
    with respx.mock(assert_all_mocked=True) as router:
        with pytest.raises(HostNotAllowedError):
            http.get_json(url)
        assert len(router.calls) == 0


def test_backoff_honours_retry_after_then_succeeds_without_real_sleep() -> None:
    sleeps: list[float] = []
    http = IntelHttp(sleep=sleeps.append, rand=lambda: 0.5)
    responses = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(500),
        httpx.Response(200, json={"ok": True}),
    ]
    with respx.mock(assert_all_mocked=True) as router:
        router.get(API).mock(side_effect=responses)
        assert http.get_json(API) == {"ok": True}
        assert len(router.calls) == 3
    assert sleeps == [2.0, 2.0]


def test_exhausted_retries_raise_upstream_error() -> None:
    sleeps: list[float] = []
    http = IntelHttp(sleep=sleeps.append, max_retries=2)
    with respx.mock(assert_all_mocked=True) as router:
        route = router.get(API).mock(return_value=httpx.Response(503))
        with pytest.raises(UpstreamError):
            http.get_json(API)
        assert route.call_count == 3
    assert len(sleeps) == 2


def test_transport_error_is_retried_then_recovers() -> None:
    sleeps: list[float] = []
    http = IntelHttp(sleep=sleeps.append)
    with respx.mock(assert_all_mocked=True) as router:
        router.get(API).mock(
            side_effect=[httpx.ConnectError("refused"), httpx.Response(200, json={})]
        )
        assert http.get_json(API) == {}
    assert len(sleeps) == 1


def test_client_error_and_redirects_are_not_followed() -> None:
    http = IntelHttp(sleep=_no_sleep)
    with respx.mock(assert_all_mocked=True) as router:
        router.get(API).mock(return_value=httpx.Response(404))
        with pytest.raises(UpstreamError):
            http.get_json(API)
    with respx.mock(assert_all_mocked=True) as router:
        router.get(API).mock(
            return_value=httpx.Response(
                302, headers={"Location": "https://evil.example/"}
            )
        )
        with pytest.raises(UpstreamError):
            http.get_json(API)


def test_minimum_interval_between_calls_is_enforced_with_injected_clock() -> None:
    now = [0.0]
    sleeps: list[float] = []
    http = IntelHttp(
        sleep=sleeps.append,
        clock=lambda: now[0],
        min_intervals={"api.osv.dev": 5.0},
    )
    with respx.mock(assert_all_mocked=True) as router:
        router.get(API).mock(return_value=httpx.Response(200, json={}))
        http.get_json(API)
        http.get_json(API)
    assert sleeps == [5.0]


def test_egress_proxy_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EGRESS_PROXY_URL", "http://proxy.test:3128")
    assert IntelHttp().proxy == "http://proxy.test:3128"
    monkeypatch.delenv("EGRESS_PROXY_URL")
    assert IntelHttp().proxy is None
