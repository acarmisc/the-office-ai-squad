from __future__ import annotations

import logging
import math
import re
import secrets
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from kubernetes.client import (
    V1Capabilities,
    V1Container,
    V1EmptyDirVolumeSource,
    V1ObjectMeta,
    V1Pod,
    V1PodSecurityContext,
    V1PodSpec,
    V1ResourceRequirements,
    V1SeccompProfile,
    V1SecurityContext,
    V1Volume,
    V1VolumeMount,
)
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream as default_stream
from kubernetes.stream.ws_client import (
    STDERR_CHANNEL,
    STDIN_CHANNEL,
    STDOUT_CHANNEL,
    V5_CHANNEL_PROTOCOL,
)

from code_squad._common.sandbox.base import (
    SMALL_OP_TIMEOUT_S,
    TIMEOUT_EXIT_CODE,
    BaseSandbox,
    ExecResult,
)
from code_squad._common.sandbox.env import SAFE_PATH, GitIdentity
from code_squad._common.sandbox.errors import SandboxError
from code_squad._common.sandbox.output import OutputCapture

WORKSPACE_DIR: Final = "/workspace"
REPO_DIR: Final = "/workspace/repo"
HOME_DIR: Final = "/workspace/.home"
TMP_DIR: Final = "/tmp"
SANDBOX_UID: Final = 10002
SANDBOX_GID: Final = 10002
CONTAINER_NAME: Final = "sandbox"
DEFAULT_ACTIVE_DEADLINE_S: Final = 1800
DEFAULT_TTL_AFTER_FINISHED_S: Final = 300
DEFAULT_STARTUP_TIMEOUT_S: Final = 180.0
KILL_AFTER_S: Final = 5
CLIENT_GRACE_S: Final = 15.0
POLL_S: Final = 0.5
POD_POLL_S: Final = 1.0
_BLOCKING_WAIT_REASONS: Final = frozenset(
    {
        "ErrImagePull",
        "ImagePullBackOff",
        "InvalidImageName",
        "CreateContainerConfigError",
        "CreateContainerError",
    }
)
_INVOCATION: Final = re.compile(r"^[a-z0-9]{1,40}$")
_RESOURCE_KEYS: Final = frozenset({"requests", "limits"})

_logger = logging.getLogger("code_squad.sandbox")


class CoreApi(Protocol):
    def create_namespaced_pod(self, namespace: str, body: V1Pod) -> Any: ...

    def read_namespaced_pod(self, name: str, namespace: str) -> Any: ...

    def delete_namespaced_pod(
        self, name: str, namespace: str, grace_period_seconds: int | None = None
    ) -> Any: ...

    def connect_get_namespaced_pod_exec(
        self, name: str, namespace: str, **kwargs: Any
    ) -> Any: ...


StreamFn = Callable[..., Any]


def sandbox_labels(invocation: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/part-of": "code-squad",
        "code-squad/sandbox": "true",
        "code-squad/invocation": invocation,
    }


def build_pod_manifest(
    *,
    name: str,
    namespace: str,
    image: str,
    resources: Mapping[str, Mapping[str, str]],
    active_deadline_seconds: int,
    labels: Mapping[str, str],
) -> V1Pod:
    seccomp = V1SeccompProfile(type="RuntimeDefault")
    container = V1Container(
        name=CONTAINER_NAME,
        image=image,
        command=["sleep", "infinity"],
        working_dir=WORKSPACE_DIR,
        stdin=False,
        tty=False,
        resources=V1ResourceRequirements(
            requests=dict(resources.get("requests", {})) or None,
            limits=dict(resources.get("limits", {})) or None,
        ),
        security_context=V1SecurityContext(
            allow_privilege_escalation=False,
            privileged=False,
            read_only_root_filesystem=True,
            run_as_non_root=True,
            run_as_user=SANDBOX_UID,
            run_as_group=SANDBOX_GID,
            capabilities=V1Capabilities(drop=["ALL"]),
            seccomp_profile=seccomp,
        ),
        volume_mounts=[
            V1VolumeMount(name="workspace", mount_path=WORKSPACE_DIR),
            V1VolumeMount(name="tmp", mount_path=TMP_DIR),
        ],
    )
    spec = V1PodSpec(
        containers=[container],
        restart_policy="Never",
        active_deadline_seconds=active_deadline_seconds,
        automount_service_account_token=False,
        enable_service_links=False,
        security_context=V1PodSecurityContext(
            run_as_non_root=True,
            run_as_user=SANDBOX_UID,
            run_as_group=SANDBOX_GID,
            fs_group=SANDBOX_GID,
            seccomp_profile=seccomp,
        ),
        volumes=[
            V1Volume(name="workspace", empty_dir=V1EmptyDirVolumeSource()),
            V1Volume(name="tmp", empty_dir=V1EmptyDirVolumeSource()),
        ],
    )
    return V1Pod(
        api_version="v1",
        kind="Pod",
        metadata=V1ObjectMeta(name=name, namespace=namespace, labels=dict(labels)),
        spec=spec,
    )


@dataclass(frozen=True)
class _Outcome:
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool
    timed_out: bool


class KubernetesJobSandbox(BaseSandbox):
    """One sandbox pod per invocation, driven through the Kubernetes exec API.

    Pods cannot use ttlSecondsAfterFinished (Job-only), so cleanup relies on destroy()
    in a finally block plus activeDeadlineSeconds as the hard stop. The
    ttl_seconds_after_finished value is recorded for a future Job-based variant.
    """

    def __init__(
        self,
        core_api: CoreApi,
        namespace: str,
        image: str,
        resources: Mapping[str, Mapping[str, str]] | None = None,
        *,
        active_deadline_seconds: int = DEFAULT_ACTIVE_DEADLINE_S,
        ttl_seconds_after_finished: int = DEFAULT_TTL_AFTER_FINISHED_S,
        labels: Mapping[str, str] | None = None,
        stream_fn: StreamFn | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
        invocation_id: str | None = None,
        allowed_extra: Iterable[str] = (),
        allowed_schemes: Sequence[str] = ("https",),
        protected_branches: Sequence[str] = ("main", "master", "develop", "release/*"),
        exec_env: Mapping[str, str] | None = None,
        git_identity: GitIdentity | None = None,
        max_output: int = 65536,
    ) -> None:
        if not 1 <= active_deadline_seconds <= 86400:
            raise ValueError("active_deadline_seconds must be between 1 and 86400")
        if ttl_seconds_after_finished < 0:
            raise ValueError("ttl_seconds_after_finished must not be negative")
        self._api = core_api
        self._namespace = namespace
        self._image = image
        self._resources = _checked_resources(resources or {})
        self._deadline = active_deadline_seconds
        self.ttl_seconds_after_finished = ttl_seconds_after_finished
        self._extra_labels = dict(labels or {})
        self._stream_fn: StreamFn = stream_fn or default_stream
        self._clock = clock
        self._sleep = sleep
        self._startup_timeout_s = startup_timeout_s
        self._invocation = invocation_id or secrets.token_hex(6)
        if not _INVOCATION.match(self._invocation):
            raise ValueError("invocation id must be 1-40 lowercase alphanumerics")
        self._pod = f"code-squad-sbx-{self._invocation}"
        super().__init__(
            path_value=SAFE_PATH,
            allowed_extra=allowed_extra,
            allowed_schemes=allowed_schemes,
            protected_branches=protected_branches,
            exec_env=exec_env,
            git_identity=git_identity,
            max_output=max_output,
        )
        self._create_pod()
        try:
            self._mkdirs(HOME_DIR)
        except SandboxError:
            self.destroy()
            raise

    @property
    def pod_name(self) -> str:
        return self._pod

    @property
    def _root_dir(self) -> str:
        return WORKSPACE_DIR

    @property
    def _repo_dir(self) -> str:
        return REPO_DIR

    @property
    def _home_dir(self) -> str:
        return HOME_DIR

    @property
    def _tmp_dir(self) -> str:
        return TMP_DIR

    def _create_pod(self) -> None:
        labels = {**self._extra_labels, **sandbox_labels(self._invocation)}
        manifest = build_pod_manifest(
            name=self._pod,
            namespace=self._namespace,
            image=self._image,
            resources=self._resources,
            active_deadline_seconds=self._deadline,
            labels=labels,
        )
        try:
            self._api.create_namespaced_pod(namespace=self._namespace, body=manifest)
        except ApiException as exc:
            raise SandboxError(f"cannot create sandbox pod: HTTP {exc.status}") from exc
        try:
            self._wait_running()
        except BaseException:
            self._delete_pod_quietly()
            raise

    def _wait_running(self) -> None:
        deadline = self._clock() + self._startup_timeout_s
        while True:
            phase, reason = self._pod_state()
            if phase == "Running":
                return
            if phase in ("Failed", "Succeeded"):
                raise SandboxError(f"sandbox pod ended before exec: {phase}")
            if reason is not None:
                raise SandboxError(f"sandbox pod cannot start: {reason}")
            if self._clock() >= deadline:
                raise SandboxError("timed out waiting for the sandbox pod to run")
            self._sleep(POD_POLL_S)

    def _pod_state(self) -> tuple[str | None, str | None]:
        try:
            pod = self._api.read_namespaced_pod(
                name=self._pod, namespace=self._namespace
            )
        except ApiException as exc:
            raise SandboxError(f"cannot read sandbox pod: HTTP {exc.status}") from exc
        status = pod.status
        if status is None:
            return None, None
        for container in status.container_statuses or []:
            waiting = container.state.waiting if container.state else None
            if waiting is not None and waiting.reason in _BLOCKING_WAIT_REASONS:
                return status.phase, str(waiting.reason)
        return status.phase, None

    def _destroy_backend(self) -> None:
        try:
            self._api.delete_namespaced_pod(
                name=self._pod, namespace=self._namespace, grace_period_seconds=0
            )
        except ApiException as exc:
            if exc.status == 404:
                return
            raise SandboxError(f"cannot delete sandbox pod: HTTP {exc.status}") from exc

    def _delete_pod_quietly(self) -> None:
        try:
            self._destroy_backend()
        except SandboxError:
            _logger.warning("sandbox pod cleanup failed", extra={"tool": "pod"})

    def _run(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        timeout_s: float,
        env: Mapping[str, str],
        capture_limit: int,
    ) -> ExecResult:
        command = _in_env(argv, cwd=cwd, env=env, timeout_s=timeout_s)
        start = self._clock()
        outcome = self._stream(
            command,
            timeout_s=timeout_s + CLIENT_GRACE_S,
            stdin=None,
            capture_limit=capture_limit,
        )
        return ExecResult(
            argv=tuple(argv),
            exit_code=outcome.exit_code,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            duration_s=self._clock() - start,
            truncated=outcome.truncated,
            timed_out=outcome.timed_out or outcome.exit_code == TIMEOUT_EXIT_CODE,
        )

    def _stream(
        self,
        command: Sequence[str],
        *,
        timeout_s: float,
        stdin: str | None,
        capture_limit: int,
    ) -> _Outcome:
        client = self._stream_fn(
            self._api.connect_get_namespaced_pod_exec,
            self._pod,
            self._namespace,
            command=list(command),
            container=CONTAINER_NAME,
            stderr=True,
            stdin=stdin is not None,
            stdout=True,
            tty=False,
            _preload_content=False,
        )
        out = OutputCapture(capture_limit)
        err = OutputCapture(capture_limit)
        try:
            if stdin is not None:
                _send_stdin(client, stdin)
            timed_out = self._pump(client, out, err, timeout_s)
            exit_code = TIMEOUT_EXIT_CODE if timed_out else _return_code(client)
        finally:
            if client.is_open():
                client.close()
        stdout, out_cut = out.render()
        stderr, err_cut = err.render()
        return _Outcome(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            truncated=out_cut or err_cut,
            timed_out=timed_out,
        )

    def _pump(
        self, client: Any, out: OutputCapture, err: OutputCapture, timeout_s: float
    ) -> bool:
        deadline = self._clock() + timeout_s
        while client.is_open():
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            client.update(timeout=min(POLL_S, remaining))
            _drain(client, out, err)
        _drain(client, out, err)
        return bool(client.is_open())

    def _get_file(self, path: str, limit: int) -> str:
        result = self._run(
            ["head", "-c", str(limit + 1), "--", path],
            cwd=WORKSPACE_DIR,
            timeout_s=SMALL_OP_TIMEOUT_S,
            env=self._base_env,
            capture_limit=limit + 1,
        )
        if result.exit_code != 0 or result.timed_out:
            raise SandboxError("cannot read sandbox file")
        if result.truncated or len(result.stdout.encode("utf-8")) > limit:
            raise SandboxError("file exceeds the read limit")
        return result.stdout

    def _put_file(self, path: str, data: bytes, mode: int) -> None:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SandboxError("only UTF-8 text can be written to the sandbox") from exc
        command = _in_env(
            ["tee", "--", path],
            cwd=WORKSPACE_DIR,
            env=self._base_env,
            timeout_s=SMALL_OP_TIMEOUT_S,
        )
        outcome = self._stream(
            command,
            timeout_s=SMALL_OP_TIMEOUT_S + CLIENT_GRACE_S,
            stdin=text,
            capture_limit=1024,
        )
        if outcome.exit_code != 0 or outcome.timed_out:
            raise SandboxError("cannot write sandbox file")
        chmod = self._run(
            ["chmod", f"{mode:o}", "--", path],
            cwd=WORKSPACE_DIR,
            timeout_s=SMALL_OP_TIMEOUT_S,
            env=self._base_env,
            capture_limit=1024,
        )
        if chmod.exit_code != 0:
            raise SandboxError("cannot set sandbox file mode")

    def _resolve(self, path: str) -> str:
        result = self._run(
            ["readlink", "-m", "--", path],
            cwd=WORKSPACE_DIR,
            timeout_s=SMALL_OP_TIMEOUT_S,
            env=self._base_env,
            capture_limit=4096,
        )
        if result.exit_code != 0 or result.timed_out:
            raise SandboxError("cannot resolve sandbox path")
        return result.stdout.strip()

    def _mkdirs(self, path: str) -> None:
        self._simple_op(["mkdir", "-p", "--", path], "cannot create directory")

    def _make_private_dir(self, path: str) -> None:
        self._simple_op(["mkdir", "-m", "700", "--", path], "cannot create private dir")

    def _remove(self, path: str, *, recursive: bool) -> None:
        flags = ["-f", "-r"] if recursive else ["-f"]
        self._simple_op(["rm", *flags, "--", path], "cannot remove sandbox path")

    def _simple_op(self, argv: list[str], message: str) -> None:
        result = self._run(
            argv,
            cwd=WORKSPACE_DIR,
            timeout_s=SMALL_OP_TIMEOUT_S,
            env=self._base_env,
            capture_limit=1024,
        )
        if result.exit_code != 0 or result.timed_out:
            raise SandboxError(message)


def _in_env(
    argv: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    timeout_s: float,
) -> list[str]:
    """Runs argv with a cleared environment, in cwd, under the in-container timeout.

    The wrapper is part of the sandbox; callers never supply it.
    """
    assignments = [f"{key}={value}" for key, value in sorted(env.items())]
    return [
        "env",
        "-i",
        "-C",
        cwd,
        *assignments,
        "timeout",
        f"--kill-after={KILL_AFTER_S}",
        str(max(1, math.ceil(timeout_s))),
        *argv,
    ]


def _send_stdin(client: Any, text: str) -> None:
    if getattr(client, "subprotocol", None) != V5_CHANNEL_PROTOCOL:
        raise SandboxError(
            "file writes need the v5 exec channel protocol (Kubernetes 1.30+)"
        )
    client.write_stdin(text)
    client.close_channel(STDIN_CHANNEL)


def _drain(client: Any, out: OutputCapture, err: OutputCapture) -> None:
    out.feed(client.read_channel(STDOUT_CHANNEL))
    err.feed(client.read_channel(STDERR_CHANNEL))


def _return_code(client: Any) -> int:
    try:
        code = client.returncode
    except Exception:
        return -1
    return code if isinstance(code, int) else -1


def _checked_resources(
    resources: Mapping[str, Mapping[str, str]],
) -> dict[str, dict[str, str]]:
    unknown = set(resources) - _RESOURCE_KEYS
    if unknown:
        raise ValueError(f"unknown resource keys: {sorted(unknown)}")
    return {
        section: {str(key): str(value) for key, value in values.items()}
        for section, values in resources.items()
    }
