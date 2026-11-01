from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from code_squad.darryl.observability_adapters import (
    MAX_SAMPLES_PER_SERIES,
    MAX_SERIES,
    AlertmanagerAdapter,
    ArgoCdAdapter,
    BackendError,
    LokiAdapter,
    NotConfiguredError,
    PrometheusAdapter,
    QueryTooLargeError,
    make_http_client,
)

BASE = "https://prom.example.test"
LOKI = "https://loki.example.test"
END = datetime(2026, 11, 1, 14, 0, tzinfo=UTC)


def _prom(max_points: int = 11000) -> PrometheusAdapter:
    return PrometheusAdapter(BASE, httpx.Client(), max_points=max_points)


def test_instant_query_parses_vector_result() -> None:
    payload = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {"pod": "checkout-1", "__name__": "up"},
                    "value": [1761999600, "0"],
                },
            ],
        },
    }
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE}/api/v1/query", params={"query": "up"}).respond(
            json=payload
        )
        result = _prom().instant("up", None)
    assert route.called
    assert len(result.series) == 1
    assert result.series[0].labels == {"pod": "checkout-1", "__name__": "up"}
    assert result.series[0].samples[0].value == "0"
    assert result.truncated is False


def test_range_query_sends_start_end_step_and_parses_matrix() -> None:
    payload = {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"code": "503"},
                    "values": [[1761998400, "1"], [1761998460, "4"]],
                }
            ],
        },
    }
    start = END - timedelta(minutes=5)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE}/api/v1/query_range").respond(json=payload)
        result = _prom().range("rate(http_requests_total[1m])", start, END, 60)
    params = route.calls[0].request.url.params
    assert params["step"] == "60"
    assert float(params["start"]) == start.timestamp()
    assert float(params["end"]) == END.timestamp()
    assert [s.value for s in result.series[0].samples] == ["1", "4"]


def test_range_query_over_point_cap_is_refused_without_a_request() -> None:
    adapter = _prom(max_points=100)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/api/v1/query_range").respond(json={})
        with pytest.raises(QueryTooLargeError, match="would return"):
            adapter.range("up", END - timedelta(days=1), END, 60)
    assert not route.called


def test_range_query_at_exactly_the_cap_is_allowed() -> None:
    payload = {"status": "success", "data": {"resultType": "matrix", "result": []}}
    adapter = _prom(max_points=61)
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE}/api/v1/query_range").respond(json=payload)
        result = adapter.range("up", END - timedelta(minutes=60), END, 60)
    assert result.series == ()


def test_range_rejects_bad_step_and_inverted_window() -> None:
    adapter = _prom()
    with pytest.raises(BackendError, match="step"):
        adapter.range("up", END - timedelta(minutes=1), END, 0)
    with pytest.raises(BackendError, match="end must be after start"):
        adapter.range("up", END, END - timedelta(minutes=1), 60)


def test_series_are_truncated_to_the_series_cap() -> None:
    rows = [
        {"metric": {"pod": f"p{i}"}, "value": [1, str(i)]}
        for i in range(MAX_SERIES + 10)
    ]
    payload = {"status": "success", "data": {"resultType": "vector", "result": rows}}
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE}/api/v1/query").respond(json=payload)
        result = _prom().instant("up", None)
    assert len(result.series) == MAX_SERIES
    assert result.truncated is True


def test_samples_are_truncated_to_the_most_recent() -> None:
    values = [[1_000 + i, str(i)] for i in range(MAX_SAMPLES_PER_SERIES + 50)]
    payload = {
        "status": "success",
        "data": {"resultType": "matrix", "result": [{"metric": {}, "values": values}]},
    }
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE}/api/v1/query_range").respond(json=payload)
        result = _prom(max_points=10_000).range("up", END - timedelta(hours=5), END, 60)
    samples = result.series[0].samples
    assert len(samples) == MAX_SAMPLES_PER_SERIES
    assert samples[-1].value == str(MAX_SAMPLES_PER_SERIES + 49)


def test_prometheus_error_status_becomes_backend_error() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE}/api/v1/query").respond(
            status_code=400,
            json={"status": "error", "errorType": "bad_data", "error": "parse error"},
        )
        with pytest.raises(BackendError, match="HTTP 400"):
            _prom().instant("up(", None)


def test_prometheus_server_error_and_network_failure_are_backend_errors() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE}/api/v1/query").respond(status_code=503, text="unavailable")
        with pytest.raises(BackendError, match="HTTP 503"):
            _prom().instant("up", None)
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE}/api/v1/query").mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(BackendError, match="request failed: ConnectError"):
            _prom().instant("up", None)


def test_unexpected_payload_shape_is_rejected() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE}/api/v1/query").respond(text="not json")
        with pytest.raises(BackendError, match="non-JSON"):
            _prom().instant("up", None)


def test_loki_query_range_parses_streams_and_caps_lines() -> None:
    payload = {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": {"app": "checkout", "container": "app"},
                    "values": [
                        ["1761998400000000000", "ERROR first"],
                        ["1761998401000000000", "ERROR second"],
                        ["1761998402000000000", "ERROR third"],
                    ],
                }
            ],
        },
    }
    adapter = LokiAdapter(LOKI, httpx.Client(), max_lines=2)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{LOKI}/loki/api/v1/query_range").respond(json=payload)
        result = adapter.query_range(
            '{app="checkout"}', END - timedelta(hours=1), END, 50
        )
    assert route.calls[0].request.url.params["limit"] == "2"
    samples = result.series[0].samples
    assert [s.value for s in samples] == ["ERROR first", "ERROR second"]
    expected = datetime.fromtimestamp(1761998400, UTC).isoformat(timespec="seconds")
    assert samples[0].time == expected
    assert result.truncated is True


def test_argo_cd_and_alertmanager_stubs_report_not_configured() -> None:
    with pytest.raises(NotConfiguredError, match="argocd is not configured"):
        ArgoCdAdapter(None).status("checkout")
    with pytest.raises(NotConfiguredError, match="alertmanager is not configured"):
        AlertmanagerAdapter(None).active()


def test_argo_cd_and_alertmanager_stubs_are_explicit_when_url_given() -> None:
    with pytest.raises(BackendError, match="not implemented"):
        ArgoCdAdapter("https://argocd.example.test").status("checkout")
    with pytest.raises(BackendError, match="not implemented"):
        AlertmanagerAdapter("https://am.example.test").active()


def test_make_http_client_accepts_egress_proxy_and_none() -> None:
    proxied = make_http_client("http://proxy.example.test:3128")
    direct = make_http_client(None)
    assert proxied.timeout.connect == 5.0
    assert direct.timeout.read == 10.0
    proxied.close()
    direct.close()
