from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final, Literal, cast

from code_squad._common.sandbox.base import Sandbox
from code_squad._common.sandbox.env import GitIdentity
from code_squad._common.sandbox.errors import SandboxError
from code_squad._common.sandbox.k8s_job import (
    DEFAULT_ACTIVE_DEADLINE_S,
    DEFAULT_TTL_AFTER_FINISHED_S,
    CoreApi,
    KubernetesJobSandbox,
    StreamFn,
)
from code_squad._common.sandbox.local_process import LocalProcessSandbox

SandboxKind = Literal["local", "kubernetes"]
DEFAULT_RESOURCES_JSON: Final = (
    '{"requests": {"cpu": "250m", "memory": "512Mi"}, '
    '"limits": {"cpu": "2", "memory": "2Gi"}}'
)


def build_sandbox(
    kind: SandboxKind,
    *,
    environ: Mapping[str, str] | None = None,
    workspace_root: Path | None = None,
    core_api: CoreApi | None = None,
    stream_fn: StreamFn | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    exec_env: Mapping[str, str] | None = None,
    allowed_extra: tuple[str, ...] = (),
    git_identity: GitIdentity | None = None,
) -> Sandbox:
    if kind == "local":
        return LocalProcessSandbox(
            workspace_root=workspace_root,
            allowed_extra=allowed_extra,
            exec_env=exec_env,
            git_identity=git_identity,
        )
    settings = _kubernetes_settings(os.environ if environ is None else environ)
    api = core_api if core_api is not None else _incluster_core_api()
    return KubernetesJobSandbox(
        api,
        settings["namespace"],
        settings["image"],
        settings["resources"],
        active_deadline_seconds=settings["deadline"],
        ttl_seconds_after_finished=settings["ttl"],
        stream_fn=stream_fn,
        clock=clock,
        sleep=sleep,
        allowed_extra=allowed_extra,
        exec_env=exec_env,
        git_identity=git_identity,
    )


def _kubernetes_settings(environ: Mapping[str, str]) -> dict[str, Any]:
    return {
        "namespace": _required(environ, "SANDBOX_NAMESPACE"),
        "image": _required(environ, "SANDBOX_IMAGE"),
        "deadline": _positive_int(
            environ, "SANDBOX_ACTIVE_DEADLINE_SECONDS", DEFAULT_ACTIVE_DEADLINE_S
        ),
        "ttl": _positive_int(
            environ,
            "SANDBOX_TTL_SECONDS_AFTER_FINISHED",
            DEFAULT_TTL_AFTER_FINISHED_S,
            allow_zero=True,
        ),
        "resources": _resources(
            environ.get("SANDBOX_RESOURCES_JSON", DEFAULT_RESOURCES_JSON)
        ),
    }


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise SandboxError(f"{name} is required for the kubernetes sandbox")
    return value


def _positive_int(
    environ: Mapping[str, str], name: str, default: int, *, allow_zero: bool = False
) -> int:
    raw = environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SandboxError(f"{name} must be an integer") from exc
    if value < 0 or (value == 0 and not allow_zero):
        raise SandboxError(f"{name} is out of range")
    return value


def _resources(raw: str) -> dict[str, dict[str, str]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SandboxError("SANDBOX_RESOURCES_JSON is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise SandboxError("SANDBOX_RESOURCES_JSON must be an object")
    result: dict[str, dict[str, str]] = {}
    for section, values in parsed.items():
        if section not in ("requests", "limits") or not isinstance(values, dict):
            raise SandboxError("SANDBOX_RESOURCES_JSON has an unknown section")
        result[section] = {
            str(key): str(value)
            for key, value in values.items()
            if isinstance(value, (str, int, float))
        }
    return result


def _incluster_core_api() -> CoreApi:
    from kubernetes import client, config

    load_incluster: Callable[[], None] = config.load_incluster_config
    load_incluster()
    return cast(CoreApi, client.CoreV1Api())
