from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from kubernetes.client import V1Pod
from kubernetes.client.exceptions import ApiException

from code_squad._common.sandbox import (
    CommandNotAllowedError,
    GitCredentials,
    KubernetesJobSandbox,
    SandboxError,
    build_sandbox,
)
from code_squad._common.sandbox.k8s_job import (
    HOME_DIR,
    REPO_DIR,
    WORKSPACE_DIR,
    build_pod_manifest,
)
from tests.sandbox.support import (
    FAKE_TOKEN,
    FakeClock,
    FakeExecSession,
    FakeKubernetes,
    Responder,
    Script,
    inner_command,
)

IMAGE = "ghcr.io/example/code-squad-sandbox-node:0.1.0"
NAMESPACE = "code-squad-sandbox"


def _responder(files: dict[str, str]) -> Responder:
    def respond(command: list[str], _stdin: str | None) -> Script:
        inner = inner_command(command)
        if inner[0] == "readlink":
            return Script(stdout=inner[-1] + "\n")
        if inner[0] == "head":
            return Script(stdout=files.get(inner[-1], ""))
        return Script()

    return respond


def _make(
    fake: FakeKubernetes, clock: FakeClock, **kwargs: Any
) -> KubernetesJobSandbox:
    return KubernetesJobSandbox(
        fake,
        NAMESPACE,
        IMAGE,
        {
            "requests": {"cpu": "250m", "memory": "512Mi"},
            "limits": {"cpu": "2", "memory": "2Gi"},
        },
        stream_fn=fake.stream,
        clock=clock,
        sleep=clock.sleep,
        invocation_id="abc123",
        **kwargs,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake(clock: FakeClock) -> FakeKubernetes:
    return FakeKubernetes(clock, responder=_responder({}))


def test_pod_manifest_is_the_hardened_sandbox_shape(
    fake: FakeKubernetes, clock: FakeClock
) -> None:
    sb = _make(fake, clock)
    assert len(fake.created) == 1
    pod = fake.created[0]
    assert pod.metadata is not None
    assert pod.metadata.name == "code-squad-sbx-abc123"
    assert pod.metadata.namespace == NAMESPACE
    assert pod.metadata.labels == {
        "app.kubernetes.io/part-of": "code-squad",
        "code-squad/sandbox": "true",
        "code-squad/invocation": "abc123",
    }
    spec = pod.spec
    assert spec is not None
    assert spec.restart_policy == "Never"
    assert spec.active_deadline_seconds == 1800
    assert spec.automount_service_account_token is False
    assert spec.enable_service_links is False
    assert spec.security_context is not None
    assert spec.security_context.run_as_non_root is True
    assert spec.security_context.run_as_user == 10002
    assert spec.security_context.fs_group == 10002
    assert spec.security_context.seccomp_profile is not None
    assert spec.security_context.seccomp_profile.type == "RuntimeDefault"
    container = spec.containers[0]
    assert container.command == ["sleep", "infinity"]
    assert container.working_dir == WORKSPACE_DIR
    sc = container.security_context
    assert sc is not None
    assert sc.allow_privilege_escalation is False
    assert sc.privileged is False
    assert sc.read_only_root_filesystem is True
    assert sc.run_as_user == 10002
    assert sc.capabilities is not None
    assert sc.capabilities.drop == ["ALL"]
    assert container.resources is not None
    assert container.resources.limits == {"cpu": "2", "memory": "2Gi"}
    mounts = {m.mount_path: m.name for m in container.volume_mounts or []}
    assert mounts == {"/workspace": "workspace", "/tmp": "tmp"}
    volumes = {v.name: v for v in spec.volumes or []}
    assert set(volumes) == {"workspace", "tmp"}
    assert all(v.empty_dir is not None for v in volumes.values())
    sb.destroy()


def test_manifest_builder_has_no_service_account_token_mount() -> None:
    pod = build_pod_manifest(
        name="p",
        namespace="n",
        image="i",
        resources={},
        active_deadline_seconds=60,
        labels={},
    )
    assert pod.spec is not None
    assert pod.spec.automount_service_account_token is False
    assert pod.spec.service_account_name is None


def test_exec_runs_in_the_repo_under_a_cleared_environment(
    fake: FakeKubernetes, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "fake-token-for-tests")
    with _make(fake, clock) as sb:
        before = len(fake.commands)
        result = sb.exec(["git", "status", "--short"])
        assert result.exit_code == 0
        command = fake.commands[before]
    assert command[:4] == ["env", "-i", "-C", REPO_DIR]
    assert f"HOME={HOME_DIR}" in command
    assert "PATH=/usr/local/bin:/usr/bin:/bin" in command
    assert not any("LLM_API_KEY" in part for part in command)
    assert command[command.index("timeout") + 3 :] == ["git", "status", "--short"]


def test_denied_commands_never_reach_the_cluster(
    fake: FakeKubernetes, clock: FakeClock
) -> None:
    with _make(fake, clock) as sb:
        before = len(fake.commands)
        with pytest.raises(CommandNotAllowedError):
            sb.exec(["sh", "-c", "id"])
        with pytest.raises(CommandNotAllowedError):
            sb.exec(["git", "push", "origin", "main"])
        assert len(fake.commands) == before


def test_write_streams_content_over_stdin_and_sets_mode(
    fake: FakeKubernetes, clock: FakeClock
) -> None:
    with _make(fake, clock) as sb:
        sb.write("src/app.ts", "export const x = 1;\n")
        tee_session = next(
            s
            for s, c in zip(fake.sessions, fake.commands, strict=True)
            if inner_command(c)[0] == "tee"
        )
        assert tee_session.stdin_received == ["export const x = 1;\n"]
        assert tee_session.closed_channels == [0]
        chmod = [
            inner_command(c) for c in fake.commands if inner_command(c)[0] == "chmod"
        ]
        assert chmod[-1] == ["chmod", "644", "--", f"{REPO_DIR}/src/app.ts"]


def test_read_is_capped_and_uses_head(clock: FakeClock) -> None:
    files = {f"{REPO_DIR}/README.md": "hello\n"}
    fake = FakeKubernetes(clock, responder=_responder(files))
    with _make(fake, clock) as sb:
        assert sb.read("README.md") == "hello\n"
        head = next(
            inner_command(c) for c in fake.commands if inner_command(c)[0] == "head"
        )
        assert head[:3] == ["head", "-c", str(1_048_576 + 1)]


def test_credentials_stay_out_of_commands_and_arrive_only_on_stdin(
    fake: FakeKubernetes, clock: FakeClock
) -> None:
    creds = GitCredentials("squad-bot", FAKE_TOKEN, "git.example.test")
    with _make(fake, clock) as sb:
        sb.clone("https://git.example.test/org/app.git", "main", creds)
        for command in fake.commands:
            assert not any(FAKE_TOKEN in part for part in command)
        token_writes = [
            s.stdin_received
            for s, c in zip(fake.sessions, fake.commands, strict=True)
            if inner_command(c)[0] == "tee"
        ]
        assert [FAKE_TOKEN + "\n"] in token_writes
        clone = next(c for c in fake.commands if "clone" in inner_command(c))
        assert any(part.startswith("GIT_ASKPASS=") for part in clone)
        assert "SQUAD_GIT_USERNAME=squad-bot" in clone
        assert any(inner_command(c)[:2] == ["rm", "-f"] for c in fake.commands)


def test_destroy_runs_in_finally_when_the_body_raises(
    fake: FakeKubernetes, clock: FakeClock
) -> None:
    with pytest.raises(RuntimeError), _make(fake, clock):
        raise RuntimeError("agent crashed")
    assert fake.deleted == [{"name": "code-squad-sbx-abc123", "grace": 0}]


def test_destroy_is_idempotent_and_404_is_swallowed(
    fake: FakeKubernetes, clock: FakeClock
) -> None:
    sb = _make(fake, clock)
    fake.delete_status = 404
    sb.destroy()
    sb.destroy()
    with pytest.raises(SandboxError):
        sb.exec(["git", "status"])


def test_other_delete_errors_are_reported(
    fake: FakeKubernetes, clock: FakeClock
) -> None:
    sb = _make(fake, clock)
    fake.delete_status = 403
    with pytest.raises(SandboxError):
        sb.destroy()


def test_pod_that_fails_to_start_is_deleted_and_construction_raises(
    clock: FakeClock,
) -> None:
    fake = FakeKubernetes(clock, responder=_responder({}), phases=("Failed",))
    with pytest.raises(SandboxError):
        _make(fake, clock)
    assert fake.deleted == [{"name": "code-squad-sbx-abc123", "grace": 0}]


def test_pod_creation_error_is_a_sandbox_error(clock: FakeClock) -> None:
    class Forbidden(FakeKubernetes):
        def create_namespaced_pod(self, namespace: str, body: V1Pod) -> V1Pod:
            raise ApiException(status=403, reason="forbidden")

    fake = Forbidden(clock)
    with pytest.raises(SandboxError):
        _make(fake, clock)


def test_timeout_is_reported_as_124_and_the_session_is_closed(
    fake: FakeKubernetes, clock: FakeClock
) -> None:
    with _make(fake, clock) as sb:
        fake.responder = lambda command, stdin: Script(hang=True)
        result = sb.exec(["make", "test"], timeout_s=5)
    assert result.timed_out is True
    assert result.exit_code == 124
    assert fake.sessions[-1].is_open() is False


def test_file_writes_require_the_v5_channel_protocol(
    fake: FakeKubernetes, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeExecSession, "subprotocol", "v4.channel.k8s.io")
    with _make(fake, clock) as sb, pytest.raises(SandboxError):
        sb.write("a.txt", "x")


def test_nonzero_exit_is_reported_not_raised_for_exec(
    clock: FakeClock,
) -> None:
    fake = FakeKubernetes(clock, responder=_responder({}))
    with _make(fake, clock) as sb:
        fake.responder = lambda c, s: Script(stderr="boom", exit_code=2)
        result = sb.exec(["make", "test"])
    assert result.exit_code == 2
    assert result.stderr == "boom"


def test_factory_builds_a_kubernetes_sandbox_from_environment(
    fake: FakeKubernetes, clock: FakeClock
) -> None:
    environ = {
        "SANDBOX_NAMESPACE": NAMESPACE,
        "SANDBOX_IMAGE": IMAGE,
        "SANDBOX_ACTIVE_DEADLINE_SECONDS": "900",
        "SANDBOX_TTL_SECONDS_AFTER_FINISHED": "120",
        "SANDBOX_RESOURCES_JSON": json.dumps(
            {"requests": {"cpu": "1"}, "limits": {"memory": "1Gi"}}
        ),
    }
    sb = build_sandbox(
        "kubernetes",
        environ=environ,
        core_api=fake,
        stream_fn=fake.stream,
        clock=clock,
        sleep=clock.sleep,
    )
    try:
        pod = fake.created[0]
        assert pod.spec is not None
        assert pod.spec.active_deadline_seconds == 900
        assert pod.spec.containers[0].image == IMAGE
        assert pod.spec.containers[0].resources is not None
        assert pod.spec.containers[0].resources.requests == {"cpu": "1"}
        assert pod.metadata is not None
        assert pod.metadata.namespace == NAMESPACE
    finally:
        sb.destroy()


@pytest.mark.parametrize(
    "environ",
    [
        {"SANDBOX_IMAGE": IMAGE},
        {"SANDBOX_NAMESPACE": NAMESPACE},
        {
            "SANDBOX_NAMESPACE": NAMESPACE,
            "SANDBOX_IMAGE": IMAGE,
            "SANDBOX_RESOURCES_JSON": "[]",
        },
        {
            "SANDBOX_NAMESPACE": NAMESPACE,
            "SANDBOX_IMAGE": IMAGE,
            "SANDBOX_ACTIVE_DEADLINE_SECONDS": "x",
        },
    ],
)
def test_factory_rejects_incomplete_or_malformed_settings(
    environ: dict[str, str], fake: FakeKubernetes, clock: FakeClock
) -> None:
    with pytest.raises(SandboxError):
        build_sandbox(
            "kubernetes",
            environ=environ,
            core_api=fake,
            stream_fn=fake.stream,
            clock=clock,
            sleep=clock.sleep,
        )
    assert fake.created == []


def test_resource_sections_are_restricted(
    fake: FakeKubernetes, clock: FakeClock
) -> None:
    with pytest.raises(ValueError):
        KubernetesJobSandbox(
            fake,
            NAMESPACE,
            IMAGE,
            {"claims": {"x": "1"}},
            stream_fn=fake.stream,
            clock=clock,
            sleep=clock.sleep,
        )


def test_factory_passes_git_identity_to_both_backends(tmp_path: Path) -> None:
    from code_squad._common.sandbox.env import GitIdentity

    identity = GitIdentity(name="pam (code-squad)", email="pam@code-squad.invalid")
    env = {"SANDBOX_NAMESPACE": "squad-sandbox", "SANDBOX_IMAGE": "sandbox:dev"}
    fake = FakeKubernetes(FakeClock())
    sandboxes = [
        build_sandbox("local", workspace_root=tmp_path, git_identity=identity),
        build_sandbox(
            "kubernetes",
            environ=env,
            core_api=fake,
            stream_fn=fake.stream,
            git_identity=identity,
        ),
    ]
    for sandbox in sandboxes:
        base_env: dict[str, str] = sandbox._base_env  # type: ignore[attr-defined]
        assert identity.email in base_env.values()
