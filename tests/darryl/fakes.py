"""Fake Kubernetes clients and observability backends for darryl tests. No network."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

from kubernetes.client.exceptions import ApiException

from code_squad._common.contract import InvocationRequest
from code_squad.darryl.k8s import ClusterReader
from code_squad.darryl.observability_adapters import (
    Alert,
    DeploymentStatus,
    QueryResult,
)

SCENARIO_DIR: Final = Path(__file__).parent / "fixtures" / "scenarios"
_OBJECT_LISTS: Final = (
    "pods",
    "deployments",
    "replicasets",
    "statefulsets",
    "daemonsets",
    "services",
    "endpoints",
    "configmaps",
    "events",
    "controllerrevisions",
)


class FakeClusterState:
    """Objects, logs and metrics, plus a record of every API call made."""

    def __init__(
        self,
        objects: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        *,
        logs: Mapping[str, str] | None = None,
        log_errors: Sequence[str] = (),
        metrics: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self.objects: dict[str, list[dict[str, Any]]] = {
            name: [dict(item) for item in (objects or {}).get(name, [])]
            for name in _OBJECT_LISTS
        }
        self.logs: dict[str, str] = dict(logs or {})
        self.log_errors: set[str] = set(log_errors)
        self.metrics: list[dict[str, Any]] | None = (
            [dict(item) for item in metrics] if metrics is not None else None
        )
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def record(self, method: str, **kwargs: Any) -> None:
        self.calls.append(
            (method, {k: v for k, v in kwargs.items() if k != "_request_timeout"})
        )

    def items(
        self, plural: str, namespace: str, selector: str | None
    ) -> dict[str, Any]:
        wanted = _parse_selector(selector)
        found = []
        for item in self.objects[plural]:
            meta = item.get("metadata", {})
            if meta.get("namespace") != namespace:
                continue
            labels = meta.get("labels", {})
            if all(labels.get(key) == value for key, value in wanted.items()):
                found.append(item)
        return {"items": found}

    def read(self, plural: str, namespace: str, name: str) -> dict[str, Any]:
        for item in self.objects[plural]:
            meta = item.get("metadata", {})
            if meta.get("name") == name and meta.get("namespace") == namespace:
                return item
        raise ApiException(status=404, reason="Not Found")


def _parse_selector(selector: str | None) -> dict[str, str]:
    if not selector:
        return {}
    pairs = [part.split("=", 1) for part in selector.split(",") if "=" in part]
    return {key.strip(): value.strip() for key, value in pairs}


class FakeCoreApi:
    def __init__(self, state: FakeClusterState) -> None:
        self._s = state

    def _list(
        self, method: str, plural: str, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        self._s.record(method, namespace=namespace, **kwargs)
        return self._s.items(plural, namespace, kwargs.get("label_selector"))

    def _read(
        self, method: str, plural: str, name: str, namespace: str
    ) -> dict[str, Any]:
        self._s.record(method, name=name, namespace=namespace)
        return self._s.read(plural, namespace, name)

    def list_namespaced_pod(self, namespace: str, **kwargs: Any) -> dict[str, Any]:
        return self._list("list_namespaced_pod", "pods", namespace, **kwargs)

    def read_namespaced_pod(
        self, name: str, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._read("read_namespaced_pod", "pods", name, namespace)

    def list_namespaced_event(self, namespace: str, **kwargs: Any) -> dict[str, Any]:
        return self._list("list_namespaced_event", "events", namespace, **kwargs)

    def read_namespaced_event(
        self, name: str, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._read("read_namespaced_event", "events", name, namespace)

    def list_namespaced_service(self, namespace: str, **kwargs: Any) -> dict[str, Any]:
        return self._list("list_namespaced_service", "services", namespace, **kwargs)

    def read_namespaced_service(
        self, name: str, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._read("read_namespaced_service", "services", name, namespace)

    def list_namespaced_endpoints(
        self, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._list("list_namespaced_endpoints", "endpoints", namespace, **kwargs)

    def read_namespaced_endpoints(
        self, name: str, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._read("read_namespaced_endpoints", "endpoints", name, namespace)

    def list_namespaced_config_map(
        self, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._list(
            "list_namespaced_config_map", "configmaps", namespace, **kwargs
        )

    def read_namespaced_config_map(
        self, name: str, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._read("read_namespaced_config_map", "configmaps", name, namespace)

    def read_namespaced_pod_log(
        self,
        name: str,
        namespace: str,
        container: str | None = None,
        previous: bool | None = None,
        **kwargs: Any,
    ) -> str:
        self._s.record(
            "read_namespaced_pod_log",
            name=name,
            namespace=namespace,
            container=container,
            previous=previous,
            **{
                k: v
                for k, v in kwargs.items()
                if k in ("tail_lines", "since_seconds", "limit_bytes")
            },
        )
        key = _log_key(name, container, bool(previous))
        if key in self._s.log_errors:
            raise ApiException(status=400, reason="Bad Request")
        return self._s.logs.get(key, "")


class FakeAppsApi:
    def __init__(self, state: FakeClusterState) -> None:
        self._s = state

    def _list(
        self, method: str, plural: str, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        self._s.record(method, namespace=namespace, **kwargs)
        return self._s.items(plural, namespace, kwargs.get("label_selector"))

    def _read(
        self, method: str, plural: str, name: str, namespace: str
    ) -> dict[str, Any]:
        self._s.record(method, name=name, namespace=namespace)
        return self._s.read(plural, namespace, name)

    def list_namespaced_deployment(
        self, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._list(
            "list_namespaced_deployment", "deployments", namespace, **kwargs
        )

    def read_namespaced_deployment(
        self, name: str, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._read("read_namespaced_deployment", "deployments", name, namespace)

    def list_namespaced_replica_set(
        self, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._list(
            "list_namespaced_replica_set", "replicasets", namespace, **kwargs
        )

    def read_namespaced_replica_set(
        self, name: str, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._read("read_namespaced_replica_set", "replicasets", name, namespace)

    def list_namespaced_stateful_set(
        self, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._list(
            "list_namespaced_stateful_set", "statefulsets", namespace, **kwargs
        )

    def read_namespaced_stateful_set(
        self, name: str, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._read(
            "read_namespaced_stateful_set", "statefulsets", name, namespace
        )

    def list_namespaced_daemon_set(
        self, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._list(
            "list_namespaced_daemon_set", "daemonsets", namespace, **kwargs
        )

    def read_namespaced_daemon_set(
        self, name: str, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._read("read_namespaced_daemon_set", "daemonsets", name, namespace)

    def list_namespaced_controller_revision(
        self, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._list(
            "list_namespaced_controller_revision",
            "controllerrevisions",
            namespace,
            **kwargs,
        )

    def read_namespaced_controller_revision(
        self, name: str, namespace: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._read(
            "read_namespaced_controller_revision",
            "controllerrevisions",
            name,
            namespace,
        )


class FakeCustomApi:
    def __init__(self, state: FakeClusterState) -> None:
        self._s = state

    def list_namespaced_custom_object(
        self, group: str, version: str, namespace: str, plural: str, **kwargs: Any
    ) -> dict[str, Any]:
        self._s.record(
            "list_namespaced_custom_object",
            group=group,
            version=version,
            namespace=namespace,
            plural=plural,
        )
        if self._s.metrics is None:
            raise ApiException(status=404, reason="Not Found")
        return {"items": self._s.metrics}


def _log_key(pod: str, container: str | None, previous: bool) -> str:
    return f"{pod}/{container or ''}/{'previous' if previous else 'current'}"


def fake_reader(
    state: FakeClusterState,
    *,
    allowed: Sequence[str],
    now: datetime | None = None,
    max_log_lines: int = 500,
    extra_patterns: Sequence[str] = (),
) -> ClusterReader:
    fixed = now or datetime.now(UTC)
    return ClusterReader(
        cast(Any, FakeCoreApi(state)),
        cast(Any, FakeAppsApi(state)),
        cast(Any, FakeCustomApi(state)),
        allowed_namespaces=list(allowed),
        max_log_lines=max_log_lines,
        extra_patterns=list(extra_patterns),
        clock=lambda: fixed,
    )


class FakeMetrics:
    def __init__(self, result: QueryResult | None = None) -> None:
        self.result = result or QueryResult((), truncated=False)
        self.calls: list[tuple[str, str]] = []

    def instant(self, query: str, at: datetime | None) -> QueryResult:
        self.calls.append(("instant", query))
        return self.result

    def range(
        self, query: str, start: datetime, end: datetime, step_seconds: int
    ) -> QueryResult:
        self.calls.append(("range", query))
        return self.result


class FakeLogs:
    def __init__(self, result: QueryResult | None = None) -> None:
        self.result = result or QueryResult((), truncated=False)
        self.calls: list[tuple[str, int]] = []

    def query_range(
        self, query: str, start: datetime, end: datetime, limit: int
    ) -> QueryResult:
        self.calls.append((query, limit))
        return self.result


class FakeDeployStatus:
    def __init__(self, status: DeploymentStatus | None = None) -> None:
        self.status_value = status

    def status(self, app: str) -> DeploymentStatus:
        if self.status_value is None:
            raise AssertionError("status should not be requested")
        return self.status_value


class FakeAlerts:
    def active(self) -> tuple[Alert, ...]:
        return ()


def load_scenario(name: str) -> dict[str, Any]:
    data: Any = json.loads((SCENARIO_DIR / f"{name}.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("scenario must be a JSON object")
    return data


def request_for(prompt: str, **overrides: Any) -> InvocationRequest:
    values: dict[str, Any] = {
        "prompt": prompt,
        "mode": "troubleshoot",
        "project": "acme/web",
    }
    values.update(overrides)
    return InvocationRequest.model_validate(values)
