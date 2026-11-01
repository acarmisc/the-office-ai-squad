from __future__ import annotations

import time
from collections.abc import Callable

import httpx
import pytest
import respx

from code_squad._common.vcs.base import NotFoundError, RateLimitedError, VcsError
from code_squad._common.vcs.http import HttpClient, tail_text

URL = "https://vcs.test/api/v4/user"


def _client(sleeps: list[float], clock: Callable[[], float] = time.time) -> HttpClient:
    return HttpClient(sleep=sleeps.append, rand=lambda: 0.0, clock=clock)


def test_429_is_retried_after_retry_after_seconds() -> None:
    sleeps: list[float] = []
    with respx.mock(assert_all_mocked=True) as router:
        router.get(URL).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "2"}),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        assert _client(sleeps).get_json(URL) == {"ok": True}
    assert sleeps == [2.0]


def test_5xx_is_retried_with_exponential_backoff() -> None:
    sleeps: list[float] = []
    with respx.mock(assert_all_mocked=True) as router:
        router.get(URL).mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(502),
                httpx.Response(200, json={}),
            ]
        )
        _client(sleeps).get_json(URL)
    assert sleeps == [1.0, 2.0]


def test_retries_are_bounded_and_then_fail_with_status() -> None:
    sleeps: list[float] = []
    with respx.mock(assert_all_mocked=True) as router:
        router.get(URL).mock(return_value=httpx.Response(500))
        with pytest.raises(VcsError) as info:
            _client(sleeps).get_json(URL)
    assert info.value.status_code == 500
    assert len(sleeps) == 4


def test_github_secondary_rate_limit_is_retried() -> None:
    sleeps: list[float] = []
    with respx.mock(assert_all_mocked=True) as router:
        router.get(URL).mock(
            side_effect=[
                httpx.Response(
                    403, headers={"retry-after": "5"}, json={"message": "abuse"}
                ),
                httpx.Response(200, json={}),
            ]
        )
        _client(sleeps).get_json(URL)
    assert sleeps == [5.0]


def test_primary_rate_limit_with_distant_reset_fails_fast() -> None:
    sleeps: list[float] = []
    reset = 1_000_000.0 + 3600
    with respx.mock(assert_all_mocked=True) as router:
        router.get(URL).mock(
            return_value=httpx.Response(
                403,
                headers={
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-reset": str(int(reset)),
                },
            )
        )
        client = _client(sleeps, clock=lambda: 1_000_000.0)
        with pytest.raises(RateLimitedError) as info:
            client.get_json(URL)
    assert sleeps == []
    assert info.value.retry_after == pytest.approx(3600.0)


def test_429_with_short_reset_is_retried_until_success() -> None:
    sleeps: list[float] = []
    with respx.mock(assert_all_mocked=True) as router:
        router.get(URL).mock(
            side_effect=[
                httpx.Response(429, headers={"x-ratelimit-remaining": "0"}),
                httpx.Response(200, json={}),
            ]
        )
        _client(sleeps).get_json(URL)
    assert len(sleeps) == 1


def test_404_maps_to_not_found_and_is_not_retried() -> None:
    sleeps: list[float] = []
    with respx.mock(assert_all_mocked=True) as router:
        route = router.get(URL).mock(
            return_value=httpx.Response(404, json={"message": "nope"})
        )
        with pytest.raises(NotFoundError):
            _client(sleeps).get_json(URL)
    assert sleeps == []
    assert route.call_count == 1


def test_plain_403_is_an_error_without_retry() -> None:
    sleeps: list[float] = []
    with respx.mock(assert_all_mocked=True) as router:
        router.get(URL).mock(
            return_value=httpx.Response(403, json={"message": "denied"})
        )
        with pytest.raises(VcsError) as info:
            _client(sleeps).get_json(URL)
    assert info.value.status_code == 403
    assert "denied" in str(info.value)
    assert sleeps == []


def test_pages_follow_link_next() -> None:
    first = "https://vcs.test/api/v4/items?page=1"
    second = "https://vcs.test/api/v4/items?page=2"
    with respx.mock(assert_all_mocked=True) as router:
        router.get(first).mock(
            return_value=httpx.Response(
                200, json=[1], headers={"Link": f'<{second}>; rel="next"'}
            )
        )
        router.get(second).mock(return_value=httpx.Response(200, json=[2]))
        items = _client([]).get_list(first)
    assert items == [1, 2]


def test_pages_follow_x_next_page_header() -> None:
    base = "https://vcs.test/api/v4/items"
    with respx.mock(assert_all_mocked=True) as router:
        router.get(base, params={"page": "1"}).mock(
            return_value=httpx.Response(200, json=["a"], headers={"x-next-page": "2"})
        )
        router.get(base, params={"page": "2"}).mock(
            return_value=httpx.Response(200, json=["b"], headers={"x-next-page": ""})
        )
        items = _client([]).get_list(base, params={"page": "1"})
    assert items == ["a", "b"]


def test_egress_proxy_env_configures_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EGRESS_PROXY_URL", "http://proxy.test:3128")
    assert HttpClient().proxy == "http://proxy.test:3128"
    assert (
        HttpClient(proxy_url="http://other.test:8080").proxy == "http://other.test:8080"
    )
    monkeypatch.delenv("EGRESS_PROXY_URL")
    assert HttpClient().proxy is None


def test_tail_text_keeps_the_last_bytes_and_valid_utf8() -> None:
    raw = "héllo world\n".encode()
    assert tail_text(raw, 6) == "world\n"
    assert tail_text(raw, 1000) == "héllo world\n"
    tail = tail_text(raw, 11)
    assert tail.endswith("\n")
