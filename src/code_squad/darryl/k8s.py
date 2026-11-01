"""Read-only Kubernetes access for darryl.

``ClusterReader`` wraps injected API clients and exposes only read operations. Each call
checks the namespace allow-list, refuses secret resources in every spelling, masks env
values and ConfigMap values, and bounds the size of its output. The module never calls
a create, patch, replace, delete or connect operation.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any, Final

from kubernetes import config as kube_config
from kubernetes.client import ApiClient, AppsV1Api, CoreV1Api, CustomObjectsApi
from kubernetes.client.exceptions import ApiException
from urllib3.exceptions import HTTPError

from code_squad.darryl.redact import EmailPolicy, redact

MAX_ITEMS: Final = 100
MAX_EVENT_FETCH: Final = 500
MAX_EVENTS: Final = 100
MAX_RELATED_EVENTS: Final = 20
MAX_HISTORY: Final = 20
MAX_CONFIGMAP_KEYS: Final = 50
MAX_LOG_BYTES: Final = 30_000
MAX_VALUE_CHARS: Final = 200
MAX_MESSAGE_CHARS: Final = 300
MAX_SINCE_MINUTES: Final = 7 * 24 * 60
MAX_SINCE_SECONDS: Final = 7 * 24 * 3600
MAX_SELECTOR_CHARS: Final = 500
REQUEST_TIMEOUT_SECONDS: Final = 10
REVISION_ANNOTATION: Final = "deployment.kubernetes.io/revision"
CHANGE_CAUSE_ANNOTATION: Final = "kubernetes.io/change-cause"
REDACTED_VALUE: Final = "<redacted>"

_NAME: Final = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")
_NAMESPACE: Final = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
_SELECTOR: Final = re.compile(r"^[A-Za-z0-9_./=,!()\- ]*$")


class K8sError(Exception):
    """A refusal or failure whose message is safe to show to the model."""


class NamespaceNotAllowedError(K8sError):
    pass


class SecretAccessRefusedError(K8sError):
    pass


class UnsupportedKindError(K8sError):
    pass


class InvalidArgumentError(K8sError):
    pass


class MetricsUnavailableError(K8sError):
    pass


@dataclass(frozen=True)
class _Kind:
    plural: str
    singular: str
    api: str
    list_method: str
    read_method: str
    summarize: Callable[[dict[str, Any]], dict[str, Any]]
    detail: bool = False


def _utc_now() -> datetime:
    return datetime.now(UTC)


@cache
def _serializer() -> ApiClient:
    return ApiClient()


def _plain(obj: object) -> dict[str, Any]:
    serializer: Any = _serializer()
    value: dict[str, Any] = serializer.sanitize_for_serialization(obj)
    return value if isinstance(value, dict) else {}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _as_list(payload.get("items")) if isinstance(item, dict)]


def _meta(obj: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(obj.get("metadata"))


def _annotations(obj: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(_meta(obj).get("annotations"))


def _clip(value: object, limit: int = MAX_VALUE_CHARS) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _state_text(state: dict[str, Any]) -> str:
    if "running" in state:
        return "running"
    terminated = _as_dict(state.get("terminated"))
    if terminated:
        reason = terminated.get("reason") or "unknown reason"
        return f"terminated: {reason} exit {terminated.get('exitCode')}"
    waiting = _as_dict(state.get("waiting"))
    if waiting:
        reason = waiting.get("reason") or "unknown reason"
        message = _clip(waiting.get("message"), MAX_MESSAGE_CHARS)
        return f"waiting: {reason}" + (f" ({message})" if message else "")
    return "none"


def _conditions(status: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": _as_dict(item).get("type"),
            "status": _as_dict(item).get("status"),
            "reason": _as_dict(item).get("reason"),
            "message": _clip(_as_dict(item).get("message"), MAX_MESSAGE_CHARS),
        }
        for item in _as_list(status.get("conditions"))
    ]


def _pod_spec(obj: dict[str, Any]) -> dict[str, Any]:
    spec = _as_dict(obj.get("spec"))
    template = _as_dict(spec.get("template"))
    return _as_dict(template.get("spec")) if template else spec


def _images(obj: dict[str, Any]) -> list[Any]:
    containers = _as_list(_pod_spec(obj).get("containers"))
    return [_as_dict(item).get("image") for item in containers]


def _container_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": status.get("name"),
        "image": _clip(status.get("image")),
        "ready": status.get("ready"),
        "restartCount": status.get("restartCount"),
        "state": _state_text(_as_dict(status.get("state"))),
        "lastState": _state_text(_as_dict(status.get("lastState"))),
    }


def _pod_summary(obj: dict[str, Any]) -> dict[str, Any]:
    status = _as_dict(obj.get("status"))
    statuses = [_as_dict(item) for item in _as_list(status.get("containerStatuses"))]
    return {
        "name": _meta(obj).get("name"),
        "phase": status.get("phase"),
        "node": _as_dict(obj.get("spec")).get("nodeName"),
        "ready": f"{sum(1 for s in statuses if s.get('ready'))}/{len(statuses)}",
        "restarts": sum(int(s.get("restartCount") or 0) for s in statuses),
        "containers": [_container_status(s) for s in statuses],
        "conditions": _conditions(status),
    }


def _deployment_summary(obj: dict[str, Any]) -> dict[str, Any]:
    spec = _as_dict(obj.get("spec"))
    status = _as_dict(obj.get("status"))
    return {
        "name": _meta(obj).get("name"),
        "replicas": spec.get("replicas"),
        "readyReplicas": status.get("readyReplicas") or 0,
        "updatedReplicas": status.get("updatedReplicas") or 0,
        "availableReplicas": status.get("availableReplicas") or 0,
        "revision": _annotations(obj).get(REVISION_ANNOTATION),
        "strategy": _as_dict(spec.get("strategy")).get("type"),
        "images": _images(obj),
        "conditions": _conditions(status),
    }


def _owner(obj: dict[str, Any]) -> dict[str, Any] | None:
    owners = [_as_dict(item) for item in _as_list(_meta(obj).get("ownerReferences"))]
    if not owners:
        return None
    return {"kind": owners[0].get("kind"), "name": owners[0].get("name")}


def _replicaset_summary(obj: dict[str, Any]) -> dict[str, Any]:
    spec = _as_dict(obj.get("spec"))
    status = _as_dict(obj.get("status"))
    return {
        "name": _meta(obj).get("name"),
        "replicas": spec.get("replicas"),
        "readyReplicas": status.get("readyReplicas") or 0,
        "revision": _annotations(obj).get(REVISION_ANNOTATION),
        "owner": _owner(obj),
        "images": _images(obj),
    }


def _statefulset_summary(obj: dict[str, Any]) -> dict[str, Any]:
    spec = _as_dict(obj.get("spec"))
    status = _as_dict(obj.get("status"))
    return {
        "name": _meta(obj).get("name"),
        "replicas": spec.get("replicas"),
        "readyReplicas": status.get("readyReplicas") or 0,
        "currentRevision": status.get("currentRevision"),
        "updateRevision": status.get("updateRevision"),
        "images": _images(obj),
    }


def _daemonset_summary(obj: dict[str, Any]) -> dict[str, Any]:
    status = _as_dict(obj.get("status"))
    return {
        "name": _meta(obj).get("name"),
        "desiredNumberScheduled": status.get("desiredNumberScheduled"),
        "numberReady": status.get("numberReady"),
        "updatedNumberScheduled": status.get("updatedNumberScheduled"),
        "numberAvailable": status.get("numberAvailable"),
        "images": _images(obj),
    }


def _service_summary(obj: dict[str, Any]) -> dict[str, Any]:
    spec = _as_dict(obj.get("spec"))
    return {
        "name": _meta(obj).get("name"),
        "type": spec.get("type"),
        "clusterIP": spec.get("clusterIP"),
        "ports": [_as_dict(item) for item in _as_list(spec.get("ports"))],
        "selector": _as_dict(spec.get("selector")),
    }


def _endpoints_summary(obj: dict[str, Any]) -> dict[str, Any]:
    subsets = [_as_dict(item) for item in _as_list(obj.get("subsets"))]
    return {
        "name": _meta(obj).get("name"),
        "subsets": [
            {
                "ready": len(_as_list(item.get("addresses"))),
                "notReady": len(_as_list(item.get("notReadyAddresses"))),
                "ports": [_as_dict(p).get("port") for p in _as_list(item.get("ports"))],
            }
            for item in subsets
        ],
    }


def _configmap_summary(obj: dict[str, Any]) -> dict[str, Any]:
    data = _as_dict(obj.get("data"))
    keys = sorted(str(key) for key in data)[:MAX_CONFIGMAP_KEYS]
    return {
        "name": _meta(obj).get("name"),
        "keys": keys,
        "data": {key: data[key] for key in keys},
    }


def _event_time_text(obj: dict[str, Any]) -> str | None:
    for key in ("lastTimestamp", "eventTime", "firstTimestamp"):
        if obj.get(key):
            return str(obj[key])
    return _meta(obj).get("creationTimestamp")


def _event_summary(obj: dict[str, Any]) -> dict[str, Any]:
    involved = _as_dict(obj.get("involvedObject"))
    return {
        "type": obj.get("type"),
        "reason": obj.get("reason"),
        "message": _clip(obj.get("message"), MAX_MESSAGE_CHARS),
        "object": f"{involved.get('kind')}/{involved.get('name')}",
        "count": obj.get("count"),
        "time": _event_time_text(obj),
    }


def _controller_revision_summary(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _meta(obj).get("name"),
        "revision": obj.get("revision"),
        "owner": _owner(obj),
    }


_Summary = Callable[[dict[str, Any]], dict[str, Any]]


def _kind(
    plural: str,
    singular: str,
    api: str,
    summarize: _Summary,
    detail: bool = False,
) -> _Kind:
    return _Kind(
        plural=plural,
        singular=singular,
        api=api,
        list_method=f"list_namespaced_{singular}",
        read_method=f"read_namespaced_{singular}",
        summarize=summarize,
        detail=detail,
    )


_KINDS: Final[dict[str, _Kind]] = {
    "pods": _kind("pods", "pod", "core", _pod_summary, detail=True),
    "deployments": _kind(
        "deployments", "deployment", "apps", _deployment_summary, True
    ),
    "replicasets": _kind(
        "replicasets", "replica_set", "apps", _replicaset_summary, True
    ),
    "statefulsets": _kind(
        "statefulsets", "stateful_set", "apps", _statefulset_summary, True
    ),
    "daemonsets": _kind("daemonsets", "daemon_set", "apps", _daemonset_summary, True),
    "services": _kind("services", "service", "core", _service_summary),
    "endpoints": _kind("endpoints", "endpoints", "core", _endpoints_summary),
    "configmaps": _kind("configmaps", "config_map", "core", _configmap_summary),
    "events": _kind("events", "event", "core", _event_summary),
    "controllerrevisions": _kind(
        "controllerrevisions",
        "controller_revision",
        "apps",
        _controller_revision_summary,
    ),
}
_SINGULAR_TO_PLURAL: Final[dict[str, str]] = {
    "pod": "pods",
    "po": "pods",
    "deployment": "deployments",
    "deploy": "deployments",
    "replicaset": "replicasets",
    "rs": "replicasets",
    "statefulset": "statefulsets",
    "sts": "statefulsets",
    "daemonset": "daemonsets",
    "ds": "daemonsets",
    "service": "services",
    "svc": "services",
    "endpoint": "endpoints",
    "ep": "endpoints",
    "configmap": "configmaps",
    "cm": "configmaps",
    "event": "events",
    "ev": "events",
    "controllerrevision": "controllerrevisions",
}
SUPPORTED_KINDS: Final = tuple(sorted(_KINDS))


def _resolve_kind(raw: str) -> _Kind:
    text = raw.strip().lower()
    if not text:
        raise InvalidArgumentError("kind is required")
    if "secret" in text:
        raise SecretAccessRefusedError(
            f"refused: kind '{raw}' is a secret resource; darryl never reads secrets"
        )
    token = text.rsplit("/", 1)[-1].split(".", 1)[0]
    plural = token if token in _KINDS else _SINGULAR_TO_PLURAL.get(token)
    if plural is None:
        raise UnsupportedKindError(
            f"unsupported kind '{raw}'; supported: {', '.join(SUPPORTED_KINDS)}"
        )
    return _KINDS[plural]


def _bounded_int(value: int, low: int, high: int, label: str) -> int:
    if not low <= value <= high:
        raise InvalidArgumentError(f"{label} must be between {low} and {high}")
    return value


def _env_view(env: Sequence[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in env:
        item = _as_dict(raw)
        row: dict[str, Any] = {"name": item.get("name")}
        if item.get("value") is not None:
            row["value"] = REDACTED_VALUE
        if "valueFrom" in item:
            row["valueFrom"] = _value_from_view(_as_dict(item["valueFrom"]))
        rows.append(row)
    return rows


def _value_from_view(source: dict[str, Any]) -> dict[str, Any]:
    view: dict[str, Any] = {}
    for key in ("configMapKeyRef", "secretKeyRef"):
        if key in source:
            ref = _as_dict(source[key])
            view[key] = {"name": ref.get("name"), "key": ref.get("key")}
    if "fieldRef" in source:
        view["fieldRef"] = _as_dict(source["fieldRef"]).get("fieldPath")
    if "resourceFieldRef" in source:
        view["resourceFieldRef"] = _as_dict(source["resourceFieldRef"]).get("resource")
    return view


def _probe_view(probe: Any) -> dict[str, Any] | None:
    if not isinstance(probe, dict):
        return None
    if "httpGet" in probe:
        http = _as_dict(probe["httpGet"])
        target = f"httpGet {http.get('path')}:{http.get('port')}"
    elif "tcpSocket" in probe:
        target = f"tcp:{_as_dict(probe['tcpSocket']).get('port')}"
    elif "grpc" in probe:
        target = "grpc"
    elif "exec" in probe:
        target = "exec"
    else:
        target = "unknown"
    return {
        "target": target,
        "initialDelaySeconds": probe.get("initialDelaySeconds"),
        "periodSeconds": probe.get("periodSeconds"),
        "timeoutSeconds": probe.get("timeoutSeconds"),
        "failureThreshold": probe.get("failureThreshold"),
    }


def _env_from_view(item: dict[str, Any]) -> dict[str, Any]:
    if "configMapRef" in item:
        return {"configMapRef": _as_dict(item["configMapRef"]).get("name")}
    return {"secretRef": _as_dict(item.get("secretRef")).get("name")}


def _container_detail(container: dict[str, Any]) -> dict[str, Any]:
    probes = {
        key: _probe_view(container.get(key))
        for key in ("livenessProbe", "readinessProbe", "startupProbe")
    }
    ports = [_as_dict(p).get("containerPort") for p in _as_list(container.get("ports"))]
    env_from = [_env_from_view(_as_dict(i)) for i in _as_list(container.get("envFrom"))]
    return {
        "name": container.get("name"),
        "image": container.get("image"),
        "resources": _as_dict(container.get("resources")),
        "ports": ports,
        "env": _env_view(_as_list(container.get("env"))),
        "envFrom": env_from,
        "probes": {key: value for key, value in probes.items() if value is not None},
    }


def _container_details(obj: dict[str, Any]) -> list[dict[str, Any]]:
    containers = _as_list(_pod_spec(obj).get("containers"))
    return [_container_detail(_as_dict(item)) for item in containers]


def _revision(obj: dict[str, Any]) -> int | None:
    text = _annotations(obj).get(REVISION_ANNOTATION)
    return int(text) if isinstance(text, str) and text.isdigit() else None


def _owned_by(obj: dict[str, Any], deployment: str) -> bool:
    return any(
        _as_dict(ref).get("kind") == "Deployment"
        and _as_dict(ref).get("name") == deployment
        for ref in _as_list(_meta(obj).get("ownerReferences"))
    )


def _recent(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    rows.sort(key=lambda row: str(row.get("time") or ""))
    return rows[-limit:]


class ClusterReader:
    """Read-only, namespace-scoped view of a cluster. No mutating method exists."""

    def __init__(
        self,
        core: CoreV1Api,
        apps: AppsV1Api,
        custom: CustomObjectsApi,
        *,
        allowed_namespaces: Sequence[str],
        max_log_lines: int = 500,
        extra_patterns: Sequence[str] = (),
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._core = core
        self._apps = apps
        self._custom = custom
        self._allowed = frozenset(allowed_namespaces)
        self._max_log_lines = max_log_lines
        self._extra = tuple(extra_patterns)
        self._clock = clock

    def get(
        self, kind: str, namespace: str, name: str = "", label_selector: str = ""
    ) -> list[dict[str, Any]]:
        spec = _resolve_kind(kind)
        ns = self._namespace(namespace)
        if name:
            return [self._finish(spec, spec.summarize(self._read(spec, ns, name)))]
        selector = _selector(label_selector)
        items = _items(self._list(spec, ns, selector, MAX_ITEMS + 1))
        rows = [self._finish(spec, spec.summarize(item)) for item in items[:MAX_ITEMS]]
        if len(items) > MAX_ITEMS:
            rows.append(
                {"truncated": f"more than {MAX_ITEMS} objects; narrow the query"}
            )
        return rows

    def describe(self, kind: str, namespace: str, name: str) -> dict[str, Any]:
        spec = _resolve_kind(kind)
        ns = self._namespace(namespace)
        obj = self._read(spec, ns, name)
        body: dict[str, Any] = {"object": self._finish(spec, spec.summarize(obj))}
        if spec.detail:
            body["containers"] = _container_details(obj)
        body["events"] = self._related_events(ns, spec, name)
        return body

    def events(self, namespace: str, since_minutes: int = 60) -> list[dict[str, Any]]:
        ns = self._namespace(namespace)
        window = _bounded_int(since_minutes, 1, MAX_SINCE_MINUTES, "since_minutes")
        cutoff = self._clock() - timedelta(minutes=window)
        rows: list[tuple[datetime, dict[str, Any]]] = []
        for item in _items(self._list(_KINDS["events"], ns, None, MAX_EVENT_FETCH)):
            moment = _parse_time(_event_time_text(item))
            if moment is not None and moment >= cutoff:
                rows.append(
                    (moment, self._finish(_KINDS["events"], _event_summary(item)))
                )
        rows.sort(key=lambda pair: pair[0])
        return [row for _, row in rows[-MAX_EVENTS:]]

    def logs(
        self,
        pod: str,
        namespace: str,
        container: str = "",
        since_seconds: int = 0,
        tail_lines: int = 200,
        previous: bool = False,
    ) -> str:
        ns = self._namespace(namespace)
        name = _name(pod)
        tail = max(1, min(tail_lines, self._max_log_lines))
        since = _bounded_int(since_seconds, 0, MAX_SINCE_SECONDS, "since_seconds")
        container_name = _name(container) if container else None
        text = self._call(
            self._core.read_namespaced_pod_log,
            name=name,
            namespace=ns,
            container=container_name,
            previous=previous,
            since_seconds=since or None,
            tail_lines=tail,
            limit_bytes=MAX_LOG_BYTES,
        )
        lines = str(text).splitlines()[-tail:]
        return "\n".join(lines)[-MAX_LOG_BYTES:]

    def top(self, namespace: str) -> list[dict[str, Any]]:
        ns = self._namespace(namespace)
        try:
            payload = self._custom.list_namespaced_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=ns,
                plural="pods",
                _request_timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except (ApiException, HTTPError, OSError) as exc:
            raise MetricsUnavailableError(
                "metrics not available: metrics.k8s.io could not be read"
            ) from exc
        rows: list[dict[str, Any]] = []
        for item in _items(_plain(payload))[:MAX_ITEMS]:
            containers = [_as_dict(c) for c in _as_list(item.get("containers"))]
            rows.append(
                {
                    "pod": _meta(item).get("name"),
                    "containers": [
                        {
                            "name": c.get("name"),
                            "cpu": _as_dict(c.get("usage")).get("cpu"),
                            "memory": _as_dict(c.get("usage")).get("memory"),
                        }
                        for c in containers
                    ],
                }
            )
        return rows

    def rollout_history(self, namespace: str, deployment: str) -> list[dict[str, Any]]:
        ns = self._namespace(namespace)
        name = _name(deployment)
        current = _revision(self._read(_KINDS["deployments"], ns, name))
        rows: list[dict[str, Any]] = []
        for rs in _items(self._list(_KINDS["replicasets"], ns, None, MAX_EVENT_FETCH)):
            revision = _revision(rs)
            if revision is None or not _owned_by(rs, name):
                continue
            spec = _as_dict(rs.get("spec"))
            status = _as_dict(rs.get("status"))
            rows.append(
                {
                    "revision": revision,
                    "current": revision == current,
                    "replicaSet": _meta(rs).get("name"),
                    "images": _images(rs),
                    "replicas": spec.get("replicas"),
                    "readyReplicas": status.get("readyReplicas") or 0,
                    "changeCause": _clip(_annotations(rs).get(CHANGE_CAUSE_ANNOTATION)),
                    "created": _meta(rs).get("creationTimestamp"),
                }
            )
        rows.sort(key=lambda row: int(row["revision"]))
        return rows[-MAX_HISTORY:]

    # ----- internals -------------------------------------------------------

    def _namespace(self, raw: str) -> str:
        if not raw:
            raise InvalidArgumentError("namespace is required")
        if not _NAMESPACE.match(raw):
            raise InvalidArgumentError("namespace is not a valid name")
        if raw not in self._allowed:
            raise NamespaceNotAllowedError(
                f"namespace not allowed: '{raw}' is not on the darryl allow-list"
            )
        return raw

    def _api(self, spec: _Kind) -> Any:
        return self._apps if spec.api == "apps" else self._core

    def _call(self, method: Callable[..., Any], **kwargs: Any) -> Any:
        try:
            return method(_request_timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
        except ApiException as exc:
            raise K8sError(
                f"kubernetes API returned {exc.status} {exc.reason or ''}".rstrip()
            ) from exc
        except HTTPError as exc:
            raise K8sError("kubernetes API is unreachable") from exc

    def _read(self, spec: _Kind, namespace: str, name: str) -> dict[str, Any]:
        method = getattr(self._api(spec), spec.read_method)
        return _plain(self._call(method, name=_name(name), namespace=namespace))

    def _list(
        self,
        spec: _Kind,
        namespace: str,
        selector: str | None,
        limit: int,
    ) -> dict[str, Any]:
        method = getattr(self._api(spec), spec.list_method)
        result = self._call(
            method,
            namespace=namespace,
            label_selector=selector,
            limit=limit,
        )
        return _plain(result)

    def _finish(self, spec: _Kind, row: dict[str, Any]) -> dict[str, Any]:
        if spec.plural != "configmaps":
            return row
        data = _as_dict(row.get("data"))
        row["data"] = {
            key: _clip(redact(str(value), self._extra, emails=EmailPolicy.MASK))
            for key, value in data.items()
        }
        return row

    def _related_events(
        self, namespace: str, spec: _Kind, name: str
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in _items(
            self._list(_KINDS["events"], namespace, None, MAX_EVENT_FETCH)
        ):
            involved = _as_dict(item.get("involvedObject"))
            if involved.get("name") != name:
                continue
            if str(involved.get("kind", "")).lower() != spec.singular.replace("_", ""):
                continue
            rows.append(_event_summary(item))
        return _recent(rows, MAX_RELATED_EVENTS)


def _name(value: str) -> str:
    if not _NAME.match(value):
        raise InvalidArgumentError(f"invalid object name '{value[:80]}'")
    return value


def _selector(value: str) -> str:
    if not value:
        return ""
    if len(value) > MAX_SELECTOR_CHARS or not _SELECTOR.match(value):
        raise InvalidArgumentError("invalid label selector")
    return value


def build_cluster_reader(
    *,
    allowed_namespaces: Sequence[str],
    max_log_lines: int = 500,
    extra_patterns: Sequence[str] = (),
) -> ClusterReader:
    """Build a reader from the in-cluster service account. Raises ConfigException."""
    loader: Any = kube_config
    loader.load_incluster_config()
    client = ApiClient()
    return ClusterReader(
        CoreV1Api(client),
        AppsV1Api(client),
        CustomObjectsApi(client),
        allowed_namespaces=allowed_namespaces,
        max_log_lines=max_log_lines,
        extra_patterns=extra_patterns,
    )


__all__ = [
    "SUPPORTED_KINDS",
    "ClusterReader",
    "InvalidArgumentError",
    "K8sError",
    "MetricsUnavailableError",
    "NamespaceNotAllowedError",
    "SecretAccessRefusedError",
    "UnsupportedKindError",
    "build_cluster_reader",
]
