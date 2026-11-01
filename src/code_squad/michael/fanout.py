"""Parallel fan-out to specialist agents over HTTP, with timeouts and circuit breakers.

Specialists are called through ``POST /invocations``. A timeout is enforced by the
fan-out itself, so a slow or hung specialist cannot hold up the consolidated result.
A transport error or 5xx is retried once with the same idempotency key. Three
consecutive failures open the circuit for an agent for a cool-down period.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

import httpx
from opentelemetry import propagate
from pydantic import ValidationError

from code_squad._common.auth import load_api_token
from code_squad._common.contract import InvocationResult, RunStatus, Verdict

OutcomeStatus = Literal["complete", "incomplete", "failed", "timed_out"]

DEFAULT_TIMEOUT_SECONDS: Final = 600
DEFAULT_PORT: Final = 8080
_ATTEMPTS: Final = 2
_MAX_KEY_LENGTH: Final = 128
_POLL_SECONDS: Final = 0.02
_CIRCUIT_THRESHOLD: Final = 3
_CIRCUIT_COOLDOWN_SECONDS: Final = 60.0


class SpecialistError(Exception):
    pass


class SpecialistTimeout(SpecialistError):
    pass


class CircuitOpenError(SpecialistError):
    pass


class SpecialistClient(Protocol):
    def bind(self, configured: Mapping[str, str]) -> SpecialistClient: ...

    def invoke(
        self,
        agent: str,
        payload: dict[str, Any],
        *,
        timeout_s: float,
        idempotency_key: str,
        trace_headers: Mapping[str, str],
    ) -> InvocationResult: ...


@dataclass(frozen=True)
class SpecialistOutcome:
    agent: str
    status: OutcomeStatus
    result: InvocationResult | None
    error: str | None
    duration_s: float

    @property
    def complete(self) -> bool:
        return self.status == "complete"


class CircuitBreaker:
    """Opens after ``threshold`` consecutive failures; after ``cooldown`` one probe call
    is allowed, and its outcome closes or reopens the circuit."""

    def __init__(
        self,
        *,
        threshold: int = _CIRCUIT_THRESHOLD,
        cooldown: float = _CIRCUIT_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._cooldown = cooldown
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._probing = False

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at < self._cooldown or self._probing:
                return False
            self._probing = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._probing = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._probing or self._failures >= self._threshold:
                self._opened_at = self._clock()
            self._probing = False


class CircuitBreakers:
    """One breaker per agent, shared by every client bound from the same root client."""

    def __init__(
        self,
        *,
        threshold: int = _CIRCUIT_THRESHOLD,
        cooldown: float = _CIRCUIT_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._options: dict[str, Any] = {
            "threshold": threshold,
            "cooldown": cooldown,
            "clock": clock,
        }
        self._lock = threading.Lock()
        self._items: dict[str, CircuitBreaker] = {}

    def get(self, agent: str) -> CircuitBreaker:
        with self._lock:
            if agent not in self._items:
                self._items[agent] = CircuitBreaker(**self._options)
            return self._items[agent]


class HttpSpecialistClient:
    """Calls ``POST {base}/invocations`` on each specialist.

    Base URLs resolve in this order: ``routing.specialist_urls`` (organisation config),
    then ``ORCHESTRATOR_SPECIALIST_URLS`` (``jim=http://...,dwight=http://...``),
    then the
    Kubernetes service name ``http://code-squad-<agent>.<namespace>.svc:8080``.
    """

    def __init__(
        self,
        http: httpx.Client,
        *,
        breakers: CircuitBreakers | None = None,
        configured: Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
        namespace: str | None = None,
    ) -> None:
        self._http = http
        self._breakers = breakers or CircuitBreakers()
        self._configured: dict[str, str] = dict(configured or {})
        self._env: dict[str, str] = dict(env or {})
        self._namespace = namespace or self._env.get("POD_NAMESPACE") or "default"
        self._token = load_api_token(self._env)

    def bind(self, configured: Mapping[str, str]) -> HttpSpecialistClient:
        return HttpSpecialistClient(
            self._http,
            breakers=self._breakers,
            configured=configured,
            env=self._env,
            namespace=self._namespace,
        )

    def base_url(self, agent: str) -> str:
        return resolve_specialist_url(
            agent, self._configured, self._env, self._namespace
        )

    def invoke(
        self,
        agent: str,
        payload: dict[str, Any],
        *,
        timeout_s: float,
        idempotency_key: str,
        trace_headers: Mapping[str, str],
    ) -> InvocationResult:
        breaker = self._breakers.get(agent)
        if not breaker.allow():
            raise CircuitOpenError(f"circuit open for {agent}")
        headers = {**trace_headers, "Idempotency-Key": idempotency_key}
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"
        body = {**payload, "idempotency_key": idempotency_key}
        url = f"{self.base_url(agent)}/invocations"
        try:
            result = self._post(url, body, headers, timeout_s)
        except SpecialistError:
            breaker.record_failure()
            raise
        breaker.record_success()
        return result

    def _post(
        self,
        url: str,
        body: dict[str, Any],
        headers: Mapping[str, str],
        timeout_s: float,
    ) -> InvocationResult:
        last: SpecialistError = SpecialistError("no response")
        for _attempt in range(_ATTEMPTS):
            try:
                response = self._http.post(
                    url, json=body, headers=dict(headers), timeout=timeout_s
                )
            except httpx.TimeoutException as exc:
                raise SpecialistTimeout(f"timed out after {timeout_s:g} s") from exc
            except httpx.TransportError as exc:
                last = SpecialistError(f"connection failed: {type(exc).__name__}")
                continue
            if response.status_code >= 500:
                last = SpecialistError(f"HTTP {response.status_code}")
                continue
            if response.status_code != 200:
                raise SpecialistError(f"HTTP {response.status_code}")
            return _parse(response)
        raise last


def resolve_specialist_url(
    agent: str,
    configured: Mapping[str, str],
    env: Mapping[str, str],
    namespace: str,
) -> str:
    if agent in configured:
        return configured[agent].rstrip("/")
    from_env = parse_url_map(env.get("ORCHESTRATOR_SPECIALIST_URLS", ""))
    if agent in from_env:
        return from_env[agent]
    return f"http://code-squad-{agent}.{namespace}.svc:{DEFAULT_PORT}"


def parse_url_map(text: str) -> dict[str, str]:
    urls: dict[str, str] = {}
    for item in text.split(","):
        key, separator, value = item.strip().partition("=")
        url = value.strip()
        if separator and key.strip() and url.startswith(("http://", "https://")):
            urls[key.strip()] = url.rstrip("/")
    return urls


def idempotency_key(base: str, agent: str) -> str:
    key = f"{base}:{agent}"
    if len(key) <= _MAX_KEY_LENGTH:
        return key
    return f"{hashlib.sha256(base.encode('utf-8')).hexdigest()}:{agent}"


def trace_headers() -> dict[str, str]:
    """W3C trace context of the current span; empty when no span is recording."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def fan_out(
    agents: Sequence[str],
    client: SpecialistClient,
    *,
    payload_for: Callable[[str], dict[str, Any]],
    key_for: Callable[[str], str],
    timeouts: Mapping[str, int],
    concurrency: int,
    trace: Mapping[str, str] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, SpecialistOutcome]:
    """Run every specialist in parallel. A specialist that runs longer than its timeout
    is reported as ``timed_out``; a queued specialist's clock starts when it begins."""
    payloads = {agent: payload_for(agent) for agent in agents}
    limits = {agent: _timeout_for(agent, timeouts) for agent in agents}
    headers = dict(trace or {})
    started: dict[str, float] = {}
    lock = threading.Lock()

    def call(agent: str) -> InvocationResult:
        with lock:
            started[agent] = clock()
        return client.invoke(
            agent,
            payloads[agent],
            timeout_s=limits[agent],
            idempotency_key=key_for(agent),
            trace_headers=headers,
        )

    executor = ThreadPoolExecutor(
        max_workers=max(1, concurrency), thread_name_prefix="michael-fanout"
    )
    waiting: dict[Future[InvocationResult], str] = {
        executor.submit(call, agent): agent for agent in agents
    }
    outcomes: dict[str, SpecialistOutcome] = {}
    try:
        while waiting:
            done, _pending = wait(
                list(waiting), timeout=_POLL_SECONDS, return_when=FIRST_COMPLETED
            )
            for future in done:
                agent = waiting.pop(future)
                outcomes[agent] = _from_future(agent, future, started, clock)
            now = clock()
            with lock:
                begun = dict(started)
            for future, agent in list(waiting.items()):
                start = begun.get(agent)
                if start is not None and now - start >= limits[agent]:
                    future.cancel()
                    del waiting[future]
                    outcomes[agent] = SpecialistOutcome(
                        agent,
                        "timed_out",
                        None,
                        f"timed out after {limits[agent]} s",
                        now - start,
                    )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return {agent: outcomes[agent] for agent in agents}


def _from_future(
    agent: str,
    future: Future[InvocationResult],
    started: Mapping[str, float],
    clock: Callable[[], float],
) -> SpecialistOutcome:
    start = started.get(agent)
    duration = clock() - start if start is not None else 0.0
    try:
        result = future.result()
    except SpecialistTimeout as exc:
        return SpecialistOutcome(agent, "timed_out", None, str(exc), duration)
    except Exception as exc:
        return SpecialistOutcome(agent, "failed", None, _describe(exc), duration)
    return SpecialistOutcome(agent, _status_of(result), result, None, duration)


def _status_of(result: InvocationResult) -> OutcomeStatus:
    if result.status is RunStatus.COMPLETE and result.verdict is not Verdict.INCOMPLETE:
        return "complete"
    if result.status is RunStatus.FAILED:
        return "failed"
    return "incomplete"


def _describe(exc: BaseException) -> str:
    if isinstance(exc, SpecialistError):
        return str(exc)
    return f"unexpected error: {type(exc).__name__}"


def _timeout_for(agent: str, timeouts: Mapping[str, int]) -> float:
    return float(timeouts.get(agent, timeouts.get("default", DEFAULT_TIMEOUT_SECONDS)))


def _parse(response: httpx.Response) -> InvocationResult:
    try:
        return InvocationResult.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise SpecialistError("invalid response from specialist") from exc
