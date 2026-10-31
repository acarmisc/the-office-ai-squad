from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final, TextIO

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span
from prometheus_client import CollectorRegistry, Counter, Histogram

from code_squad._common.contract import InvocationResult
from code_squad._common.tool_policy import ToolClass, UnclassifiedToolError, classify

REGISTRY: Final = CollectorRegistry(auto_describe=True)

INVOCATIONS: Final = Counter(
    "squad_invocations",
    "Invocations by agent and status.",
    ["agent", "status"],
    registry=REGISTRY,
)
INVOCATION_SECONDS: Final = Histogram(
    "squad_invocation_seconds",
    "Invocation wall-clock duration in seconds.",
    ["agent"],
    registry=REGISTRY,
)
ITERATIONS: Final = Histogram(
    "squad_iterations",
    "Model iterations per invocation.",
    ["agent"],
    buckets=(1, 2, 3, 5, 8, 13, 21, 34, 55),
    registry=REGISTRY,
)
TOKENS: Final = Counter(
    "squad_tokens",
    "Model tokens by agent and kind.",
    ["agent", "kind"],
    registry=REGISTRY,
)
TOOL_CALLS: Final = Counter(
    "squad_tool_calls",
    "Tool calls by agent, tool and tool class.",
    ["agent", "tool", "tool_class"],
    registry=REGISTRY,
)
FINDINGS: Final = Counter(
    "squad_findings",
    "Findings produced by agent and severity.",
    ["agent", "severity"],
    registry=REGISTRY,
)
DRY_RUN: Final = Counter(
    "squad_dry_run",
    "External write attempts blocked by dry-run.",
    ["agent"],
    registry=REGISTRY,
)
CVE_CACHE_HITS: Final = Counter(
    "squad_cve_cache_hits",
    "CVE lookup cache hits.",
    registry=REGISTRY,
)
CONFIG_RELOAD_FAILURES: Final = Counter(
    "squad_config_reload_failures",
    "Rejected configuration reloads.",
    registry=REGISTRY,
)
VCS_ERRORS: Final = Counter(
    "squad_vcs_errors",
    "VCS provider errors by provider and operation.",
    ["provider", "operation"],
    registry=REGISTRY,
)

_LOG_FIELDS: Final = (
    "agent",
    "status",
    "duration_ms",
    "iterations",
    "tool",
    "invocation_id",
)
_TRACER_NAME: Final = "code_squad"
_SAFE_SPAN_ATTRIBUTES: Final = frozenset(
    {
        "agent",
        "status",
        "iterations",
        "tool",
        "invocation_id",
        "duration_ms",
        "stop_reason",
    }
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in _LOG_FIELDS:
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        return json.dumps(entry, default=str)


class _JsonHandler(logging.StreamHandler[TextIO]):
    pass


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if not any(isinstance(handler, _JsonHandler) for handler in root.handlers):
        handler = _JsonHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    root.setLevel(level.upper())


def configure_tracing(service_name: str) -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


@contextmanager
def span(name: str, **attributes: str | int | float | bool) -> Iterator[Span]:
    unsafe = sorted(set(attributes) - _SAFE_SPAN_ATTRIBUTES)
    if unsafe:
        raise ValueError(f"span attributes not allowed: {', '.join(unsafe)}")
    tracer = trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span(name, attributes=attributes) as current:
        yield current


def record_result(result: InvocationResult, duration_seconds: float) -> None:
    agent = result.agent
    INVOCATIONS.labels(agent=agent, status=result.status.value).inc()
    INVOCATION_SECONDS.labels(agent=agent).observe(duration_seconds)
    ITERATIONS.labels(agent=agent).observe(result.stats.iterations)
    TOKENS.labels(agent=agent, kind="input").inc(result.stats.input_tokens)
    TOKENS.labels(agent=agent, kind="output").inc(result.stats.output_tokens)
    for name, count in result.stats.tool_calls.items():
        tool_class = _known_tool_class(name)
        if tool_class is not None:
            TOOL_CALLS.labels(agent=agent, tool=name, tool_class=tool_class.value).inc(
                count
            )
    for finding in result.findings:
        FINDINGS.labels(agent=agent, severity=finding.severity.value).inc()


def _known_tool_class(name: str) -> ToolClass | None:
    try:
        return classify(name)
    except UnclassifiedToolError:
        return None
