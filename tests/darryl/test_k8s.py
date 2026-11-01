from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from kubernetes.client.exceptions import ApiException

from code_squad.darryl import k8s
from code_squad.darryl.k8s import (
    ClusterReader,
    InvalidArgumentError,
    K8sError,
    MetricsUnavailableError,
    NamespaceNotAllowedError,
    SecretAccessRefusedError,
    UnsupportedKindError,
)
from tests.darryl.fakes import FakeClusterState, fake_reader

NOW = datetime(2026, 11, 1, 14, 10, tzinfo=UTC)
NS = "shop"


def _pod(
    name: str = "checkout-1",
    *,
    env: list[dict[str, Any]] | None = None,
    state: dict[str, Any] | None = None,
    last: dict[str, Any] | None = None,
    annotations: dict[str, str] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "name": name,
        "namespace": NS,
        "labels": {"app": "checkout"},
    }
    if annotations:
        meta["annotations"] = annotations
    container: dict[str, Any] = {
        "name": "app",
        "image": "registry.example.test/shop/checkout:2.4.1",
        "env": env if env is not None else [],
        "resources": {"limits": {"memory": "512Mi"}},
        "readinessProbe": {"httpGet": {"path": "/healthz", "port": 8080}},
    }
    status: dict[str, Any] = {
        "phase": "Running",
        "containerStatuses": [
            {
                "name": "app",
                "image": container["image"],
                "ready": False,
                "restartCount": 3,
                "state": state or {"running": {}},
                "lastState": last or {},
            }
        ],
    }
    return {"metadata": meta, "spec": {"containers": [container]}, "status": status}


def _reader(state: FakeClusterState, allowed: list[str] | None = None) -> ClusterReader:
    return fake_reader(state, allowed=[NS] if allowed is None else allowed, now=NOW)


def test_empty_allow_list_denies_every_namespace() -> None:
    state = FakeClusterState({"pods": [_pod()]})
    reader = _reader(state, allowed=[])
    with pytest.raises(NamespaceNotAllowedError, match="namespace not allowed"):
        reader.get("pods", NS)
    assert state.calls == []


def test_namespace_outside_allow_list_is_refused_before_any_api_call() -> None:
    state = FakeClusterState({"pods": [_pod()]})
    reader = _reader(state)
    with pytest.raises(NamespaceNotAllowedError, match="namespace not allowed"):
        reader.describe("pods", "kube-system", "checkout-1")
    assert state.calls == []


@pytest.mark.parametrize(
    "kind",
    [
        "Secret",
        "secret",
        "secrets",
        "v1/Secret",
        "v1/secrets",
        "Secret.v1",
        "SealedSecret",
    ],
)
def test_secret_kinds_are_refused_in_every_spelling(kind: str) -> None:
    state = FakeClusterState()
    reader = _reader(state)
    with pytest.raises(SecretAccessRefusedError, match="secret resource"):
        reader.get(kind, NS)
    with pytest.raises(SecretAccessRefusedError):
        reader.describe(kind, NS, "checkout-secrets")
    assert state.calls == []


def test_unsupported_kind_is_refused_with_supported_list() -> None:
    with pytest.raises(UnsupportedKindError, match="supported:"):
        _reader(FakeClusterState()).get("nodes", NS)


def test_kind_aliases_resolve_to_the_same_resource() -> None:
    state = FakeClusterState(
        {"deployments": [{"metadata": {"name": "a", "namespace": NS}}]}
    )
    reader = _reader(state)
    assert reader.get("deploy", NS)[0]["name"] == "a"
    assert reader.get("deployments.apps", NS)[0]["name"] == "a"


def test_env_literal_values_are_masked_and_references_kept() -> None:
    env: list[dict[str, Any]] = [
        {"name": "DB_HOST", "value": "checkout-db.shop.svc"},
        {"name": "DB_PASS_HINT", "value": "fake-token-for-tests"},
        {
            "name": "PAYMENT_TOKEN",
            "valueFrom": {
                "secretKeyRef": {"name": "checkout-secrets", "key": "payment-token"}
            },
        },
    ]
    state = FakeClusterState({"pods": [_pod(env=env)]})
    described = _reader(state).describe("pods", NS, "checkout-1")
    text = json.dumps(described)
    assert "fake-token-for-tests" not in text
    assert "checkout-db.shop.svc" not in text
    env_view = described["containers"][0]["env"]
    assert env_view[0] == {"name": "DB_HOST", "value": "<redacted>"}
    assert env_view[2]["valueFrom"] == {
        "secretKeyRef": {"name": "checkout-secrets", "key": "payment-token"}
    }


def test_last_applied_annotation_is_never_surfaced() -> None:
    annotation = (
        '{"spec":{"containers":[{"env":[{"name":"X","value":"leaked-value-1"}]}]}}'
    )
    state = FakeClusterState(
        {
            "pods": [
                _pod(
                    annotations={
                        "kubectl.kubernetes.io/last-applied-configuration": annotation
                    }
                )
            ]
        }
    )
    reader = _reader(state)
    assert "leaked-value-1" not in json.dumps(reader.get("pods", NS))
    assert "leaked-value-1" not in json.dumps(reader.describe("pods", NS, "checkout-1"))


def test_configmap_values_are_redacted_and_truncated() -> None:
    config = {
        "metadata": {"name": "app-config", "namespace": NS},
        "data": {
            "settings.yaml": "log: info\npassword: hunter2\n",
            "long.txt": "x" * 1000,
        },
    }
    state = FakeClusterState({"configmaps": [config]})
    rows = _reader(state).get("configmaps", NS, "app-config")
    data = rows[0]["data"]
    assert "hunter2" not in data["settings.yaml"]
    assert "password: <redacted>" in data["settings.yaml"]
    assert len(data["long.txt"]) <= k8s.MAX_VALUE_CHARS + 3


def test_extra_redaction_patterns_apply_to_configmap_values() -> None:
    config = {
        "metadata": {"name": "c", "namespace": NS},
        "data": {"ticket": "ACME-123456"},
    }
    reader = fake_reader(
        FakeClusterState({"configmaps": [config]}),
        allowed=[NS],
        now=NOW,
        extra_patterns=[r"ACME-[0-9]{6}"],
    )
    assert "ACME-123456" not in json.dumps(reader.get("configmaps", NS, "c"))


def test_describe_surfaces_oomkilled_as_last_termination_reason() -> None:
    pod = _pod(
        state={"running": {"startedAt": "2026-11-01T14:09:00+00:00"}},
        last={"terminated": {"reason": "OOMKilled", "exitCode": 137}},
    )
    described = _reader(FakeClusterState({"pods": [pod]})).describe(
        "pods", NS, "checkout-1"
    )
    status = described["object"]["containers"][0]
    assert status["lastState"] == "terminated: OOMKilled exit 137"
    assert described["object"]["restarts"] == 3


def test_describe_surfaces_crashloop_and_imagepull_waiting_reasons() -> None:
    crash = _pod(
        "crash-1",
        state={"waiting": {"reason": "CrashLoopBackOff", "message": "back-off"}},
        last={"terminated": {"reason": "Error", "exitCode": 1}},
    )
    pull = _pod(
        "pull-1",
        state={
            "waiting": {
                "reason": "ImagePullBackOff",
                "message": "Back-off pulling image",
            }
        },
    )
    reader = _reader(FakeClusterState({"pods": [crash, pull]}))
    crash_text = json.dumps(reader.describe("pods", NS, "crash-1"))
    pull_text = json.dumps(reader.describe("pods", NS, "pull-1"))
    assert "waiting: CrashLoopBackOff" in crash_text
    assert "terminated: Error exit 1" in crash_text
    assert "waiting: ImagePullBackOff" in pull_text


def test_describe_includes_related_events_only() -> None:
    events = [
        {
            "metadata": {"name": "e1", "namespace": NS},
            "involvedObject": {"kind": "Pod", "name": "checkout-1"},
            "type": "Warning",
            "reason": "BackOff",
            "message": "Back-off restarting failed container",
            "lastTimestamp": "2026-11-01T14:09:00+00:00",
        },
        {
            "metadata": {"name": "e2", "namespace": NS},
            "involvedObject": {"kind": "Pod", "name": "other-pod"},
            "type": "Warning",
            "reason": "Unrelated",
            "message": "not for this pod",
            "lastTimestamp": "2026-11-01T14:09:00+00:00",
        },
    ]
    state = FakeClusterState({"pods": [_pod()], "events": events})
    described = _reader(state).describe("pods", NS, "checkout-1")
    reasons = [event["reason"] for event in described["events"]]
    assert reasons == ["BackOff"]


def test_events_are_windowed_sorted_and_capped() -> None:
    events = []
    for index in range(150):
        minute = 14 * 60 + 9 - (index % 50)
        events.append(
            {
                "metadata": {"name": f"e{index}", "namespace": NS},
                "involvedObject": {"kind": "Pod", "name": "p"},
                "type": "Normal",
                "reason": f"R{index}",
                "message": "m",
                "lastTimestamp": (
                    f"2026-11-01T{minute // 60:02d}:{minute % 60:02d}:00+00:00"
                ),
            }
        )
    events.append(
        {
            "metadata": {"name": "old", "namespace": NS},
            "involvedObject": {"kind": "Pod", "name": "p"},
            "type": "Normal",
            "reason": "OutsideWindow",
            "message": "m",
            "lastTimestamp": "2026-10-30T00:00:00+00:00",
        }
    )
    reader = _reader(FakeClusterState({"events": events}))
    rows = reader.events(NS, since_minutes=60)
    reasons = [row["reason"] for row in rows]
    assert "OutsideWindow" not in reasons
    assert len(rows) == k8s.MAX_EVENTS
    times = [row["time"] for row in rows]
    assert times == sorted(times)


def test_events_reject_out_of_range_window() -> None:
    with pytest.raises(InvalidArgumentError):
        _reader(FakeClusterState()).events(NS, since_minutes=0)


def test_logs_are_capped_by_configured_line_limit() -> None:
    lines = "\n".join(f"line {i}" for i in range(50))
    state = FakeClusterState(logs={"checkout-1/app/current": lines})
    reader = fake_reader(state, allowed=[NS], now=NOW, max_log_lines=5)
    text = reader.logs("checkout-1", NS, container="app", tail_lines=500)
    assert text.splitlines() == [f"line {i}" for i in range(45, 50)]
    recorded = state.calls[-1][1]
    assert recorded["tail_lines"] == 5


def test_logs_are_capped_in_bytes() -> None:
    big = "y" * 200_000
    state = FakeClusterState(logs={"checkout-1/app/current": big})
    text = _reader(state).logs("checkout-1", NS, container="app", tail_lines=10)
    assert len(text.encode("utf-8")) <= k8s.MAX_LOG_BYTES


def test_previous_flag_reads_previous_container_logs() -> None:
    state = FakeClusterState(
        logs={
            "checkout-1/app/previous": "FATAL missing DATABASE_URL",
            "checkout-1/app/current": "now",
        }
    )
    text = _reader(state).logs("checkout-1", NS, container="app", previous=True)
    assert text == "FATAL missing DATABASE_URL"
    assert state.calls[-1][1]["previous"] is True


def test_api_error_is_reported_without_response_body() -> None:
    state = FakeClusterState(log_errors=["checkout-1/app/current"])
    with pytest.raises(K8sError, match="kubernetes API returned 400 Bad Request"):
        _reader(state).logs("checkout-1", NS, container="app")


def test_top_reports_metrics_not_available_on_api_error() -> None:
    with pytest.raises(MetricsUnavailableError, match="metrics not available"):
        _reader(FakeClusterState(metrics=None)).top(NS)


def test_top_lists_pod_usage_when_metrics_exist() -> None:
    metrics = [
        {
            "metadata": {"name": "checkout-1", "namespace": NS},
            "containers": [{"name": "app", "usage": {"cpu": "12m", "memory": "508Mi"}}],
        }
    ]
    rows = _reader(FakeClusterState(metrics=metrics)).top(NS)
    assert rows == [
        {
            "pod": "checkout-1",
            "containers": [{"name": "app", "cpu": "12m", "memory": "508Mi"}],
        }
    ]


def _rs(
    revision: str, image: str, owner: str = "checkout", cause: str = ""
) -> dict[str, Any]:
    annotations = {"deployment.kubernetes.io/revision": revision}
    if cause:
        annotations["kubernetes.io/change-cause"] = cause
    return {
        "metadata": {
            "name": f"{owner}-rs-{revision}",
            "namespace": NS,
            "annotations": annotations,
            "ownerReferences": [{"kind": "Deployment", "name": owner}],
            "creationTimestamp": "2026-11-01T10:00:00+00:00",
        },
        "spec": {
            "replicas": 1,
            "template": {"spec": {"containers": [{"name": "app", "image": image}]}},
        },
        "status": {"readyReplicas": 1},
    }


def test_rollout_history_orders_revisions_numerically() -> None:
    replicasets = [
        _rs("10", "img:10", cause="release ten"),
        _rs("2", "img:2"),
        _rs("9", "img:9"),
        _rs("4", "img:4", owner="other"),
        {
            "metadata": {
                "name": "checkout-no-rev",
                "namespace": NS,
                "ownerReferences": [{"kind": "Deployment", "name": "checkout"}],
            },
            "spec": {},
            "status": {},
        },
    ]
    deployment = {
        "metadata": {
            "name": "checkout",
            "namespace": NS,
            "annotations": {"deployment.kubernetes.io/revision": "10"},
        },
    }
    state = FakeClusterState({"deployments": [deployment], "replicasets": replicasets})
    rows = _reader(state).rollout_history(NS, "checkout")
    assert [row["revision"] for row in rows] == [2, 9, 10]
    assert rows[-1]["current"] is True
    assert rows[-1]["changeCause"] == "release ten"
    assert rows[0]["images"] == ["img:2"]


def test_reader_exposes_no_mutating_method() -> None:
    names = [name for name in dir(ClusterReader) if not name.startswith("_")]
    forbidden = ("create", "patch", "delete", "replace", "connect", "exec")
    assert names
    for name in names:
        assert not name.startswith(forbidden), name


def test_api_403_is_translated_to_a_short_message() -> None:
    class Denied:
        def read_namespaced_pod(self, **kwargs: Any) -> Any:
            raise ApiException(status=403, reason="Forbidden")

    reader = ClusterReader(
        cast(Any, Denied()),
        cast(Any, Denied()),
        cast(Any, Denied()),
        allowed_namespaces=[NS],
    )
    with pytest.raises(K8sError, match="kubernetes API returned 403 Forbidden"):
        reader.describe("pods", NS, "checkout-1")


@pytest.mark.parametrize("name", ["bad name", "a;rm -rf", "UPPER", "x" * 300])
def test_invalid_object_names_are_rejected(name: str) -> None:
    with pytest.raises(InvalidArgumentError):
        _reader(FakeClusterState()).describe("pods", NS, name)


def test_label_selector_filters_objects() -> None:
    pods = [_pod("a"), _pod("b")]
    pods[1]["metadata"]["labels"] = {"app": "other"}
    rows = _reader(FakeClusterState({"pods": pods})).get(
        "pods", NS, label_selector="app=checkout"
    )
    assert [row["name"] for row in rows] == ["a"]
