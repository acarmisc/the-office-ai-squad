"""Builds darryl's operations services from configuration and the pod environment.

Each backend is built on its own. A backend that is not configured is omitted. A backend
that fails to build is omitted and recorded in ``config_warnings``. Nothing here raises
for a missing optional backend.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

from kubernetes.config.config_exception import ConfigException

from code_squad._common.config.schema import OpsConfig
from code_squad.darryl.k8s import build_cluster_reader
from code_squad.darryl.observability_adapters import (
    ArgoCdAdapter,
    LokiAdapter,
    PrometheusAdapter,
    make_http_client,
)

SERVICE_HOST_ENV: Final = "KUBERNETES_SERVICE_HOST"
PROXY_ENV: Final = "EGRESS_PROXY_URL"
CLUSTER_WARNING: Final = (
    "cluster access disabled: in-cluster configuration could not be loaded"
)


def build_ops_services(
    ops_config: OpsConfig | None,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Return the darryl service entries for ``current().services``."""
    environ: Mapping[str, str] = env if env is not None else os.environ
    ops = ops_config or OpsConfig()
    services: dict[str, object] = {"ops_config": ops_config}
    warnings: list[str] = []
    cluster = _cluster(ops, environ, warnings)
    if cluster is not None:
        services["cluster"] = cluster
    proxy = environ.get(PROXY_ENV) or None
    if ops.prometheus_url:
        services["metrics"] = PrometheusAdapter(
            ops.prometheus_url,
            make_http_client(proxy),
            max_points=ops.max_query_points,
        )
    if ops.loki_url:
        services["logs_backend"] = LokiAdapter(
            ops.loki_url, make_http_client(proxy), max_lines=ops.max_log_lines
        )
    if ops.argocd_url:
        services["deploy_status"] = ArgoCdAdapter(ops.argocd_url)
    if warnings:
        services["config_warnings"] = warnings
    return services


def _cluster(
    ops: OpsConfig, environ: Mapping[str, str], warnings: list[str]
) -> object | None:
    if not environ.get(SERVICE_HOST_ENV):
        return None
    try:
        return build_cluster_reader(
            allowed_namespaces=ops.allowed_namespaces,
            max_log_lines=ops.max_log_lines,
            extra_patterns=ops.redaction_patterns,
        )
    except (ConfigException, OSError, ValueError) as exc:
        warnings.append(f"{CLUSTER_WARNING} ({type(exc).__name__})")
        return None


__all__ = ["build_ops_services"]
