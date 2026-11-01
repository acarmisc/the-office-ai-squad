from __future__ import annotations

import os
import random
import time
from collections.abc import Callable, Mapping
from typing import Any, Final

import httpx

DEFAULT_ALLOWED_HOSTS: Final = frozenset(
    {
        "api.osv.dev",
        "services.nvd.nist.gov",
        "www.cisa.gov",
        "api.first.org",
        "api.github.com",
    }
)
PROXY_ENV: Final = "EGRESS_PROXY_URL"
TIMEOUT_SECONDS: Final = 15.0
MAX_RETRIES: Final = 3
RETRY_STATUSES: Final = frozenset({429, 500, 502, 503, 504})
_BACKOFF_BASE: Final = 1.0
_BACKOFF_CAP: Final = 60.0
_USER_AGENT: Final = "code-squad-dwight/0.1"

Sleep = Callable[[float], None]
Clock = Callable[[], float]


class IntelError(Exception):
    """A vulnerability-data source could not answer."""


class HostNotAllowedError(IntelError):
    """A request targeted a host outside the allow-list."""


class UpstreamError(IntelError):
    """An upstream answered with an error, or retries were exhausted."""


class IntelHttp:
    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS,
        client: httpx.Client | None = None,
        proxy_url: str | None = None,
        max_retries: int = MAX_RETRIES,
        min_intervals: Mapping[str, float] | None = None,
        sleep: Sleep = time.sleep,
        clock: Clock = time.monotonic,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self.proxy: str | None = proxy_url or os.environ.get(PROXY_ENV) or None
        self._client = client or httpx.Client(
            timeout=TIMEOUT_SECONDS,
            proxy=self.proxy,
            follow_redirects=False,
            headers={"User-Agent": _USER_AGENT},
        )
        self._allowed = allowed_hosts
        self._max_retries = max_retries
        self._min_intervals: dict[str, float] = dict(min_intervals or {})
        self._sleep = sleep
        self._clock = clock
        self._rand = rand
        self._last_call: dict[str, float] = {}

    def close(self) -> None:
        self._client.close()

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        return self._json(self.request("GET", url, params=params, headers=headers))

    def post_json(
        self,
        url: str,
        body: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = self.request("POST", url, headers=headers, json=dict(body))
        return self._json(response)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        host = self._check_host(url)
        attempt = 0
        while True:
            self._throttle(host)
            try:
                response = self._client.request(
                    method, url, params=params, headers=headers, json=json
                )
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise UpstreamError(
                        f"{host} unreachable ({type(exc).__name__})"
                    ) from exc
                self._sleep(self._backoff(attempt, None))
                attempt += 1
                continue
            if response.status_code not in RETRY_STATUSES:
                return _checked(host, response)
            if attempt >= self._max_retries:
                raise UpstreamError(f"{host} answered {response.status_code}")
            self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
            attempt += 1

    def _check_host(self, url: str) -> str:
        parsed = httpx.URL(url)
        host = parsed.host
        if parsed.scheme != "https" or host not in self._allowed:
            raise HostNotAllowedError(f"host not allowed: {host or 'unknown'}")
        return host

    def _throttle(self, host: str) -> None:
        interval = self._min_intervals.get(host, 0.0)
        last = self._last_call.get(host)
        if interval > 0 and last is not None:
            wait = last + interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_call[host] = self._clock()

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            try:
                return min(max(float(retry_after), 0.0), _BACKOFF_CAP)
            except ValueError:
                pass
        base = min(_BACKOFF_BASE * float(2**attempt), _BACKOFF_CAP)
        return base * (0.5 + self._rand())

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(f"{response.url.host} returned invalid JSON") from exc


def _checked(host: str, response: httpx.Response) -> httpx.Response:
    if response.status_code >= 300:
        raise UpstreamError(f"{host} answered {response.status_code}")
    return response
