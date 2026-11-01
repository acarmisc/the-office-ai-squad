from __future__ import annotations

import os
import random
import re
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Final
from urllib.parse import urlsplit

import httpx

from code_squad._common.observability import VCS_ERRORS
from code_squad._common.vcs.base import NotFoundError, RateLimitedError, VcsError

TIMEOUT_SECONDS: Final = 30.0
MAX_RETRIES: Final = 4
MAX_WAIT_SECONDS: Final = 120.0
MAX_PAGES: Final = 100
_BACKOFF_CAP: Final = 30.0
_PROXY_ENV: Final = "EGRESS_PROXY_URL"
_ERROR_DETAIL_CHARS: Final = 200
_RESOURCE: Final = re.compile(r"[a-z][a-z_-]{0,31}")
_VERSION_SEGMENT: Final = re.compile(r"v\d+")

Headers = Mapping[str, str]
Params = Mapping[str, Any]


class HttpClient:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        rand: Callable[[], float] = random.random,
        proxy_url: str | None = None,
        max_retries: int = MAX_RETRIES,
        provider: str = "unknown",
    ) -> None:
        self.proxy: str | None = proxy_url or os.environ.get(_PROXY_ENV) or None
        self._provider = provider
        self._client = client or httpx.Client(
            timeout=TIMEOUT_SECONDS, proxy=self.proxy, follow_redirects=True
        )
        self._sleep = sleep
        self._clock = clock
        self._rand = rand
        self._max_retries = max_retries

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Headers | None = None,
        params: Params | None = None,
        json: Any = None,
    ) -> httpx.Response:
        try:
            return self._send(method, url, headers=headers, params=params, json=json)
        except NotFoundError:
            raise
        except (VcsError, httpx.HTTPError):
            VCS_ERRORS.labels(self._provider, operation_label(method, url)).inc()
            raise

    def _send(
        self,
        method: str,
        url: str,
        *,
        headers: Headers | None,
        params: Params | None,
        json: Any,
    ) -> httpx.Response:
        attempt = 0
        while True:
            response = self._client.request(
                method, url, headers=headers, params=params, json=json
            )
            wait = self._retry_wait(response, attempt)
            if wait is None:
                return _check(response)
            if attempt >= self._max_retries or wait > MAX_WAIT_SECONDS:
                raise _exhausted(response, wait)
            self._sleep(wait)
            attempt += 1

    def get_json(
        self, url: str, *, headers: Headers | None = None, params: Params | None = None
    ) -> Any:
        return self.request("GET", url, headers=headers, params=params).json()

    def pages(
        self, url: str, *, headers: Headers | None = None, params: Params | None = None
    ) -> Iterator[httpx.Response]:
        next_url: str | None = url
        next_params = params
        fetched = 0
        while next_url is not None:
            if fetched >= MAX_PAGES:
                raise VcsError("pagination limit reached")
            response = self.request(
                "GET", next_url, headers=headers, params=next_params
            )
            fetched += 1
            yield response
            next_url = _next_url(response)
            next_params = None

    def get_list(
        self,
        url: str,
        *,
        headers: Headers | None = None,
        params: Params | None = None,
        key: str | None = None,
    ) -> list[Any]:
        items: list[Any] = []
        for response in self.pages(url, headers=headers, params=params):
            data = response.json()
            if key is not None:
                data = as_dict(data).get(key, [])
            items.extend(as_list(data))
        return items

    def _retry_wait(self, response: httpx.Response, attempt: int) -> float | None:
        status = response.status_code
        if status >= 500 or status == 429:
            return _retry_after(response) or self._backoff(attempt)
        if status == 403 and _is_rate_limited(response):
            return self._rate_wait(response, attempt)
        return None

    def _rate_wait(self, response: httpx.Response, attempt: int) -> float:
        explicit = _retry_after(response)
        if explicit is not None:
            return explicit
        reset = _header_float(response, "x-ratelimit-reset")
        if reset is not None:
            return max(0.0, reset - self._clock())
        return self._backoff(attempt)

    def _backoff(self, attempt: int) -> float:
        return min(_BACKOFF_CAP, float(2**attempt)) + self._rand() * 0.5


def operation_label(method: str, url: str) -> str:
    """Bounded metric label: the method and the first API resource, never the URL."""
    segments = [
        segment
        for segment in urlsplit(url).path.split("/")
        if segment and segment != "api" and not _VERSION_SEGMENT.fullmatch(segment)
    ]
    resource = segments[0] if segments else ""
    if not _RESOURCE.fullmatch(resource):
        resource = "other"
    return f"{method.upper()} {resource}"


def as_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VcsError("unexpected response shape from VCS API")
    return {str(key): item for key, item in value.items()}


def as_list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise VcsError("unexpected response shape from VCS API")
    return list(value)


def tail_text(raw: bytes, max_bytes: int) -> str:
    tail = raw[-max_bytes:] if max_bytes > 0 else b""
    while tail and (tail[0] & 0xC0) == 0x80:
        tail = tail[1:]
    return tail.decode("utf-8", errors="replace")


def _check(response: httpx.Response) -> httpx.Response:
    if response.status_code == 404:
        raise NotFoundError(f"not found: {_path(response)}")
    if response.status_code >= 400:
        raise VcsError(
            f"HTTP {response.status_code} from {_path(response)}: {_detail(response)}",
            status_code=response.status_code,
        )
    return response


def _exhausted(response: httpx.Response, wait: float | None) -> VcsError:
    status = response.status_code
    if status == 429 or (status == 403 and _is_rate_limited(response)):
        return RateLimitedError(
            f"rate limited by {_path(response)}",
            retry_after=wait,
            status_code=status,
        )
    return VcsError(f"HTTP {status} from {_path(response)}", status_code=status)


def _is_rate_limited(response: httpx.Response) -> bool:
    if response.headers.get("retry-after") is not None:
        return True
    return bool(response.headers.get("x-ratelimit-remaining") == "0")


def _retry_after(response: httpx.Response) -> float | None:
    return _header_float(response, "retry-after")


def _header_float(response: httpx.Response, name: str) -> float | None:
    raw = response.headers.get(name)
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _next_url(response: httpx.Response) -> str | None:
    link = response.links.get("next")
    if link is not None:
        return str(link["url"])
    next_page = response.headers.get("x-next-page")
    if not next_page:
        return None
    return str(response.request.url.copy_set_param("page", next_page))


def _path(response: httpx.Response) -> str:
    return response.request.url.path


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict) and isinstance(body.get("message"), str):
        return str(body["message"])[:_ERROR_DETAIL_CHARS]
    return ""
