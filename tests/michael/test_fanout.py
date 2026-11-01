from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider

from code_squad._common.contract import InvocationResult, RunStatus, Verdict
from code_squad.michael.fanout import (
    CircuitBreaker,
    CircuitBreakers,
    CircuitOpenError,
    HttpSpecialistClient,
    SpecialistError,
    SpecialistTimeout,
    fan_out,
    idempotency_key,
    parse_url_map,
    resolve_specialist_url,
    trace_headers,
)
from tests.michael.support import FakeSpecialists, result_for

PAYLOAD: dict[str, Any] = {"prompt": "Review.", "mode": "review", "post": False}


def _ok(agent: str) -> InvocationResult:
    return result_for(agent)


def _body(agent: str, verdict: str = "approve") -> dict[str, Any]:
    return {
        "agent": agent,
        "status": "complete",
        "verdict": verdict,
        "summary": f"{agent} finished.",
        "findings": [],
    }


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# ----- fan-out -----------------------------------------------------------------


def test_specialists_run_in_parallel_not_one_after_another() -> None:
    def slow(agent: str) -> Callable[[dict[str, Any]], InvocationResult]:
        def run(_payload: dict[str, Any]) -> InvocationResult:
            time.sleep(0.3)
            return _ok(agent)

        return run

    fake = FakeSpecialists({name: slow(name) for name in ("jim", "angela", "dwight")})
    started = time.monotonic()
    outcomes = fan_out(
        ["jim", "angela", "dwight"],
        fake,
        payload_for=lambda _agent: dict(PAYLOAD),
        key_for=lambda agent: f"k:{agent}",
        timeouts={"default": 5},
        concurrency=3,
    )
    elapsed = time.monotonic() - started
    assert elapsed < 0.8, f"fan-out took {elapsed:.2f}s; expected parallel execution"
    assert {name: item.status for name, item in outcomes.items()} == {
        "jim": "complete",
        "angela": "complete",
        "dwight": "complete",
    }


def test_concurrency_limit_bounds_parallel_calls() -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def tracked(agent: str) -> Callable[[dict[str, Any]], InvocationResult]:
        def run(_payload: dict[str, Any]) -> InvocationResult:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return _ok(agent)

        return run

    names = ["jim", "angela", "dwight", "darryl"]
    fake = FakeSpecialists({name: tracked(name) for name in names})
    fan_out(
        names,
        fake,
        payload_for=lambda _agent: dict(PAYLOAD),
        key_for=lambda agent: agent,
        timeouts={"default": 5},
        concurrency=2,
    )
    assert peak == 2


def test_per_agent_timeout_marks_the_agent_timed_out_without_waiting() -> None:
    release = threading.Event()

    def hangs(_payload: dict[str, Any]) -> InvocationResult:
        release.wait(5)
        return _ok("angela")

    fake = FakeSpecialists({"angela": hangs, "jim": _ok("jim")})
    try:
        started = time.monotonic()
        outcomes = fan_out(
            ["jim", "angela"],
            fake,
            payload_for=lambda _agent: dict(PAYLOAD),
            key_for=lambda agent: agent,
            timeouts={"default": 600, "angela": 1},
            concurrency=2,
        )
        elapsed = time.monotonic() - started
    finally:
        release.set()
    assert elapsed < 4
    assert outcomes["angela"].status == "timed_out"
    assert outcomes["angela"].result is None
    assert outcomes["angela"].error == "timed out after 1.0 s"
    assert outcomes["jim"].status == "complete"


def test_queued_specialist_clock_starts_when_it_begins() -> None:
    def quick(agent: str) -> Callable[[dict[str, Any]], InvocationResult]:
        def run(_payload: dict[str, Any]) -> InvocationResult:
            time.sleep(0.2)
            return _ok(agent)

        return run

    fake = FakeSpecialists({name: quick(name) for name in ("jim", "angela")})
    outcomes = fan_out(
        ["jim", "angela"],
        fake,
        payload_for=lambda _agent: dict(PAYLOAD),
        key_for=lambda agent: agent,
        timeouts={"default": 1},
        concurrency=1,
    )
    assert outcomes["angela"].status == "complete"


def test_exception_becomes_a_failed_outcome_with_its_reason() -> None:
    fake = FakeSpecialists({"dwight": SpecialistError("HTTP 503"), "jim": _ok("jim")})
    outcomes = fan_out(
        ["jim", "dwight"],
        fake,
        payload_for=lambda _agent: dict(PAYLOAD),
        key_for=lambda agent: agent,
        timeouts={"default": 5},
        concurrency=2,
    )
    assert outcomes["dwight"].status == "failed"
    assert outcomes["dwight"].error == "HTTP 503"
    assert outcomes["jim"].complete


def test_unexpected_exception_is_reported_by_type_only() -> None:
    fake = FakeSpecialists({"jim": KeyError("secret-looking-detail")})
    outcomes = fan_out(
        ["jim"],
        fake,
        payload_for=lambda _agent: dict(PAYLOAD),
        key_for=lambda agent: agent,
        timeouts={"default": 5},
        concurrency=1,
    )
    assert outcomes["jim"].status == "failed"
    assert outcomes["jim"].error == "unexpected error: KeyError"


def test_incomplete_result_is_not_complete() -> None:
    incomplete = result_for(
        "jim", verdict=Verdict.INCOMPLETE, status=RunStatus.INCOMPLETE
    )
    failed = result_for("dwight", verdict=Verdict.INCOMPLETE, status=RunStatus.FAILED)
    fake = FakeSpecialists({"jim": incomplete, "dwight": failed})
    outcomes = fan_out(
        ["jim", "dwight"],
        fake,
        payload_for=lambda _agent: dict(PAYLOAD),
        key_for=lambda agent: agent,
        timeouts={"default": 5},
        concurrency=2,
    )
    assert outcomes["jim"].status == "incomplete"
    assert outcomes["dwight"].status == "failed"


def test_payloads_and_idempotency_keys_are_passed_per_agent() -> None:
    fake = FakeSpecialists({"jim": _ok("jim"), "angela": _ok("angela")})
    fan_out(
        ["jim", "angela"],
        fake,
        payload_for=lambda agent: {"prompt": agent, "post": False},
        key_for=lambda agent: idempotency_key("abc", agent),
        timeouts={"default": 7},
        concurrency=2,
        trace={"traceparent": "00-x-y-01"},
    )
    jim = fake.call_for("jim")
    assert jim.payload == {"prompt": "jim", "post": False}
    assert jim.idempotency_key == "abc:jim"
    assert jim.timeout_s == 7.0
    assert jim.trace_headers == {"traceparent": "00-x-y-01"}


# ----- circuit breaker --------------------------------------------------------


def test_breaker_opens_after_three_failures_and_probes_after_cooldown() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(threshold=3, cooldown=60, clock=clock)
    for _ in range(2):
        assert breaker.allow()
        breaker.record_failure()
    assert breaker.allow()
    breaker.record_failure()
    assert not breaker.allow()
    clock.now += 59
    assert not breaker.allow()
    clock.now += 2
    assert breaker.allow()
    assert not breaker.allow(), "only one probe may run while half-open"
    breaker.record_success()
    assert breaker.allow()


def test_failed_probe_reopens_the_circuit_for_another_cooldown() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(threshold=1, cooldown=10, clock=clock)
    breaker.record_failure()
    clock.now += 10
    assert breaker.allow()
    breaker.record_failure()
    assert not breaker.allow()
    clock.now += 10
    assert breaker.allow()


def test_success_resets_the_failure_count() -> None:
    breaker = CircuitBreaker(threshold=3, cooldown=60, clock=_Clock())
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.allow()


# ----- HTTP client -------------------------------------------------------------


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    clock: _Clock | None = None,
    env: dict[str, str] | None = None,
    configured: dict[str, str] | None = None,
) -> HttpSpecialistClient:
    breakers = CircuitBreakers(clock=clock or _Clock())
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpSpecialistClient(
        http, breakers=breakers, env=env, configured=configured, namespace=None
    )


def _invoke(
    client: HttpSpecialistClient, agent: str = "jim", key: str = "k1"
) -> InvocationResult:
    return client.invoke(
        agent,
        dict(PAYLOAD),
        timeout_s=5,
        idempotency_key=key,
        trace_headers={"traceparent": "00-aa-bb-01"},
    )


def test_http_client_posts_to_the_service_with_keys_and_trace_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_body("jim"))

    result = _invoke(_client(handler, env={"POD_NAMESPACE": "squad"}), key="abc:jim")
    assert result.agent == "jim"
    request = seen[0]
    assert str(request.url) == "http://code-squad-jim.squad.svc:8080/invocations"
    assert request.headers["idempotency-key"] == "abc:jim"
    assert request.headers["traceparent"] == "00-aa-bb-01"
    body = json.loads(request.content)
    assert body["post"] is False
    assert body["idempotency_key"] == "abc:jim"


def test_transient_5xx_is_retried_once_with_the_same_idempotency_key() -> None:
    keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers["idempotency-key"])
        if len(keys) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=_body("jim"))

    assert _invoke(_client(handler), key="same").agent == "jim"
    assert keys == ["same", "same"]


def test_connection_error_is_retried_then_reported() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(SpecialistError, match="connection failed: ConnectError"):
        _invoke(_client(handler))
    assert calls == 2


def test_client_error_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(422, json={"detail": "bad"})

    with pytest.raises(SpecialistError, match="HTTP 422"):
        _invoke(_client(handler))
    assert calls == 1


def test_timeout_is_raised_as_a_timeout_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(SpecialistTimeout):
        _invoke(_client(handler))
    assert calls == 1


def test_invalid_response_body_is_a_specialist_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(SpecialistError, match="invalid response"):
        _invoke(_client(handler))


def test_circuit_opens_after_three_failed_calls_and_recovers_after_cooldown() -> None:
    clock = _Clock()
    calls = 0
    healthy = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if healthy:
            return httpx.Response(200, json=_body("jim"))
        return httpx.Response(500)

    client = _client(handler, clock=clock)
    for _ in range(3):
        with pytest.raises(SpecialistError):
            _invoke(client)
    calls_before = calls
    with pytest.raises(CircuitOpenError):
        _invoke(client)
    assert calls == calls_before, "an open circuit must not send a request"

    clock.now += 61
    healthy = True
    assert _invoke(client).agent == "jim"
    assert _invoke(client).agent == "jim"


def test_breakers_are_per_agent() -> None:
    clock = _Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        if "code-squad-jim" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(200, json=_body("dwight"))

    client = _client(handler, clock=clock)
    for _ in range(3):
        with pytest.raises(SpecialistError):
            _invoke(client, "jim")
    assert _invoke(client, "dwight").agent == "dwight"


# ----- URL resolution and trace context ---------------------------------------


def test_url_resolution_prefers_config_then_env_then_service_dns() -> None:
    env = {
        "ORCHESTRATOR_SPECIALIST_URLS": "jim=http://env-jim:9000/, dwight=http://env-dwight:9000"
    }
    configured = {"jim": "https://config-jim.example.com/"}
    assert resolve_specialist_url("jim", configured, env, "squad") == (
        "https://config-jim.example.com"
    )
    assert resolve_specialist_url("dwight", configured, env, "squad") == (
        "http://env-dwight:9000"
    )
    assert resolve_specialist_url("darryl", configured, env, "squad") == (
        "http://code-squad-darryl.squad.svc:8080"
    )


def test_url_map_ignores_malformed_and_non_http_entries() -> None:
    assert parse_url_map(
        "jim=http://a:1, broken, =http://x, pam=ftp://nope, dwight=https://b"
    ) == {
        "jim": "http://a:1",
        "dwight": "https://b",
    }


def test_namespace_defaults_to_pod_namespace_then_default() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(200, json=_body("jim"))

    http = httpx.Client(transport=httpx.MockTransport(handler))
    _invoke(HttpSpecialistClient(http, env={}))
    _invoke(HttpSpecialistClient(http, env={"POD_NAMESPACE": "review"}))
    assert seen == ["code-squad-jim.default.svc", "code-squad-jim.review.svc"]


def test_trace_headers_carry_the_current_span_context() -> None:
    provider = TracerProvider()
    tracer = provider.get_tracer("michael-tests")
    assert trace_headers() == {}
    with tracer.start_as_current_span("fan-out"):
        headers = trace_headers()
    assert headers["traceparent"].startswith("00-")


def test_idempotency_key_is_bounded_to_128_characters() -> None:
    long_base = "x" * 300
    key = idempotency_key(long_base, "darryl")
    assert len(key) <= 128
    assert key.endswith(":darryl")
    assert idempotency_key("short", "jim") == "short:jim"
