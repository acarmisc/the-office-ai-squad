"""Pluggable observability backends for darryl, enabled only by configuration.

Protocols describe what the troubleshooting tools need. Prometheus and Loki have working
HTTP adapters with result caps. Argo CD and Alertmanager are stubs: they report "not
configured" without a URL and "not implemented" with one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol, runtime_checkable

import httpx

MAX_SERIES: Final = 20
MAX_SAMPLES_PER_SERIES: Final = 300
MAX_RESPONSE_BYTES: Final = 5_000_000
MAX_LOKI_LINES: Final = 5000
_ERROR_CHARS: Final = 300


class BackendError(Exception):
    """A backend failure whose message is safe to show to the model."""


class NotConfiguredError(BackendError):
    pass


class QueryTooLargeError(BackendError):
    pass


@dataclass(frozen=True)
class Sample:
    time: str
    value: str


@dataclass(frozen=True)
class Series:
    labels: dict[str, str]
    samples: tuple[Sample, ...]


@dataclass(frozen=True)
class QueryResult:
    series: tuple[Series, ...]
    truncated: bool


@dataclass(frozen=True)
class DeploymentStatus:
    app: str
    sync: str
    health: str
    revision: str
    message: str


@dataclass(frozen=True)
class Alert:
    name: str
    severity: str
    state: str
    starts_at: str
    summary: str


@runtime_checkable
class MetricsBackend(Protocol):
    def instant(self, query: str, at: datetime | None) -> QueryResult: ...

    def range(
        self, query: str, start: datetime, end: datetime, step_seconds: int
    ) -> QueryResult: ...


@runtime_checkable
class LogsBackend(Protocol):
    def query_range(
        self, query: str, start: datetime, end: datetime, limit: int
    ) -> QueryResult: ...


@runtime_checkable
class DeploymentStatusBackend(Protocol):
    def status(self, app: str) -> DeploymentStatus: ...


@runtime_checkable
class AlertsBackend(Protocol):
    def active(self) -> tuple[Alert, ...]: ...


def make_http_client(proxy_url: str | None = None) -> httpx.Client:
    """HTTP client with bounded timeouts, optionally through the egress proxy."""
    return httpx.Client(
        timeout=httpx.Timeout(10.0, connect=5.0),
        proxy=proxy_url or None,
        follow_redirects=False,
    )


def _unix(moment: datetime) -> str:
    return f"{moment.timestamp():.3f}"


def _join(base: str, path: str) -> str:
    return base.rstrip("/") + path


def _json_object(response: httpx.Response) -> dict[str, Any]:
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise BackendError("backend response is too large")
    try:
        data: Any = response.json()
    except ValueError as exc:
        raise BackendError("backend returned a non-JSON response") from exc
    if not isinstance(data, dict):
        raise BackendError("backend returned an unexpected response shape")
    return data


def _get(http: httpx.Client, system: str, url: str, params: dict[str, str]) -> Any:
    try:
        response = http.get(url, params=params)
    except httpx.HTTPError as exc:
        raise BackendError(f"{system} request failed: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        detail = response.text[:_ERROR_CHARS] if response.status_code < 500 else ""
        raise BackendError(f"{system} returned HTTP {response.status_code} {detail}")
    return _json_object(response)


class PrometheusAdapter:
    """Prometheus HTTP API (`/api/v1/query` and `/api/v1/query_range`)."""

    def __init__(
        self,
        base_url: str,
        http: httpx.Client,
        *,
        max_points: int,
        max_series: int = MAX_SERIES,
        max_samples: int = MAX_SAMPLES_PER_SERIES,
    ) -> None:
        self._base = base_url
        self._http = http
        self._max_points = max_points
        self._max_series = max_series
        self._max_samples = max_samples

    def instant(self, query: str, at: datetime | None) -> QueryResult:
        params = {"query": query}
        if at is not None:
            params["time"] = _unix(at)
        data = _get(
            self._http, "prometheus", _join(self._base, "/api/v1/query"), params
        )
        return self._parse(data)

    def range(
        self, query: str, start: datetime, end: datetime, step_seconds: int
    ) -> QueryResult:
        if step_seconds < 1:
            raise BackendError("step must be at least 1 second")
        span = (end - start).total_seconds()
        if span <= 0:
            raise BackendError("end must be after start")
        points = int(span // step_seconds) + 1
        if points > self._max_points:
            raise QueryTooLargeError(
                f"query would return {points} points per series; the limit is "
                f"{self._max_points}. Increase the step or shorten the range."
            )
        params = {
            "query": query,
            "start": _unix(start),
            "end": _unix(end),
            "step": str(step_seconds),
        }
        url = _join(self._base, "/api/v1/query_range")
        return self._parse(_get(self._http, "prometheus", url, params))

    def _parse(self, data: dict[str, Any]) -> QueryResult:
        if data.get("status") != "success":
            error = str(data.get("error", "unknown error"))[:_ERROR_CHARS]
            raise BackendError(f"prometheus query failed: {error}")
        body = data.get("data")
        if not isinstance(body, dict):
            raise BackendError("prometheus returned an unexpected response shape")
        kind = body.get("resultType")
        rows = body.get("result")
        if not isinstance(rows, list):
            raise BackendError("prometheus returned an unexpected response shape")
        series = [self._series(kind, row) for row in rows[: self._max_series]]
        return QueryResult(tuple(series), truncated=len(rows) > self._max_series)

    def _series(self, kind: object, row: object) -> Series:
        if not isinstance(row, dict):
            raise BackendError("prometheus returned an unexpected series")
        labels = {str(k): str(v) for k, v in dict(row.get("metric") or {}).items()}
        if kind == "matrix":
            pairs = list(row.get("values") or [])
            samples = [_sample(pair) for pair in pairs[-self._max_samples :]]
        else:
            samples = [_sample(row.get("value") or [])]
        return Series(labels, tuple(samples))


def _sample(pair: object) -> Sample:
    if not isinstance(pair, list | tuple) or len(pair) != 2:
        raise BackendError("prometheus returned an unexpected sample")
    return Sample(time=str(pair[0]), value=str(pair[1]))


class LokiAdapter:
    """Loki HTTP API (`/loki/api/v1/query_range`) with a line cap."""

    def __init__(
        self,
        base_url: str,
        http: httpx.Client,
        *,
        max_lines: int = MAX_LOKI_LINES,
    ) -> None:
        self._base = base_url
        self._http = http
        self._max_lines = min(max_lines, MAX_LOKI_LINES)

    def query_range(
        self, query: str, start: datetime, end: datetime, limit: int
    ) -> QueryResult:
        capped = max(1, min(limit, self._max_lines))
        params = {
            "query": query,
            "start": str(int(start.timestamp() * 1e9)),
            "end": str(int(end.timestamp() * 1e9)),
            "limit": str(capped),
            "direction": "backward",
        }
        url = _join(self._base, "/loki/api/v1/query_range")
        data = _get(self._http, "loki", url, params)
        return _parse_loki(data, capped)


def _parse_loki(data: dict[str, Any], limit: int) -> QueryResult:
    if data.get("status") != "success":
        raise BackendError("loki query failed")
    body = data.get("data")
    if not isinstance(body, dict) or not isinstance(body.get("result"), list):
        raise BackendError("loki returned an unexpected response shape")
    series: list[Series] = []
    remaining = limit
    truncated = False
    for stream in body["result"]:
        if not isinstance(stream, dict) or remaining <= 0:
            truncated = truncated or remaining <= 0
            continue
        labels = {str(k): str(v) for k, v in dict(stream.get("stream") or {}).items()}
        samples: list[Sample] = []
        for entry in list(stream.get("values") or []):
            if remaining <= 0:
                truncated = True
                break
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            samples.append(Sample(time=_loki_time(str(entry[0])), value=str(entry[1])))
            remaining -= 1
        series.append(Series(labels, tuple(samples)))
    return QueryResult(tuple(series), truncated=truncated)


def _loki_time(nanos: str) -> str:
    if not nanos.isdigit():
        return nanos
    moment = datetime.fromtimestamp(int(nanos) / 1e9, tz=UTC)
    return moment.isoformat(timespec="seconds")


class ArgoCdAdapter:
    """Argo CD status. Stub: needs an API token that this version does not configure."""

    def __init__(self, base_url: str | None) -> None:
        self._base = base_url

    def status(self, app: str) -> DeploymentStatus:
        if not self._base:
            raise NotConfiguredError("argocd is not configured")
        raise BackendError(
            f"argocd status for '{app}' is not implemented in this version"
        )


class AlertmanagerAdapter:
    """Alertmanager alerts. Stub: returns "not configured" without a URL."""

    def __init__(self, base_url: str | None) -> None:
        self._base = base_url

    def active(self) -> tuple[Alert, ...]:
        if not self._base:
            raise NotConfiguredError("alertmanager is not configured")
        raise BackendError("alertmanager alerts are not implemented in this version")
