from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from code_squad._common.sandbox import (
    CommandNotAllowedError,
    GitCredentials,
    LocalProcessSandbox,
    PathEscapeError,
    SandboxError,
)
from code_squad._common.sandbox.base import TIMEOUT_EXIT_CODE
from code_squad._common.sandbox.env import SAFE_PATH, GitIdentity
from tests.sandbox.support import (
    FAKE_TOKEN,
    FAKE_USER,
    git_head_commit,
    make_bare_repo,
    run_git,
    start_git_http,
)

IDENTITY = GitIdentity("Squad Bot", "squad-bot@example.test")
NODE = shutil.which("node")


@pytest.fixture
def bare(tmp_path: Path) -> Path:
    return make_bare_repo(tmp_path / "remote")


@pytest.fixture
def sandbox(tmp_path: Path, bare: Path) -> Iterator[LocalProcessSandbox]:
    sb = LocalProcessSandbox(
        tmp_path / "workspaces",
        allowed_schemes=("file", "http"),
        git_identity=IDENTITY,
    )
    try:
        sb.clone(f"file://{bare}", "main", None)
        yield sb
    finally:
        sb.destroy()


def test_clone_then_exec_git_status_runs_inside_the_repo(
    sandbox: LocalProcessSandbox,
) -> None:
    result = sandbox.exec(["git", "status", "--short"])
    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.timed_out is False


def test_write_read_and_diff_round_trip(sandbox: LocalProcessSandbox) -> None:
    sandbox.write("src/feature.txt", "hello\n")
    assert sandbox.read("src/feature.txt") == "hello\n"
    diff = sandbox.diff()
    assert "+++ b/src/feature.txt" in diff
    assert "+hello" in diff


def test_apply_patch_reapplies_a_diff_after_reset(sandbox: LocalProcessSandbox) -> None:
    sandbox.write("README.md", "hello\nchanged\n")
    patch = sandbox.diff()
    sandbox.exec(["git", "checkout", "--", "."])
    assert sandbox.read("README.md") == "hello\n"
    result = sandbox.apply_patch(patch)
    assert result.exit_code == 0
    assert sandbox.read("README.md") == "hello\nchanged\n"


def test_apply_patch_refuses_paths_that_escape(sandbox: LocalProcessSandbox) -> None:
    patch = "--- a/../../outside.txt\n+++ b/../../outside.txt\n@@ -0,0 +1 @@\n+x\n"
    with pytest.raises(SandboxError):
        sandbox.apply_patch(patch)


def test_read_and_write_refuse_traversal_and_symlink_escape(
    tmp_path: Path, sandbox: LocalProcessSandbox
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("nope\n")
    os.symlink(outside, Path(sandbox._repo_dir) / "link")
    for rel in ("../x", "/etc/passwd"):
        with pytest.raises(PathEscapeError):
            sandbox.read(rel)
    with pytest.raises(SandboxError):
        sandbox.read("link/secret.txt")
    with pytest.raises(SandboxError):
        sandbox.write("link/new.txt", "x")


def test_writes_into_git_metadata_are_refused(sandbox: LocalProcessSandbox) -> None:
    with pytest.raises(PathEscapeError):
        sandbox.write(".git/hooks/pre-commit", "#!/bin/sh\nexit 0\n")
    with pytest.raises(PathEscapeError):
        sandbox.write("sub/.git/config", "[core]\n")


def test_git_clone_push_and_config_are_not_reachable_through_exec(
    sandbox: LocalProcessSandbox,
) -> None:
    for argv in (
        ["git", "clone", "file:///tmp/x"],
        ["git", "push", "origin", "main"],
        ["git", "config", "core.hooksPath", "/tmp"],
        ["sh", "-c", "id"],
    ):
        with pytest.raises(CommandNotAllowedError):
            sandbox.exec(argv)


def test_push_never_uses_force_and_refuses_protected_branches(
    sandbox: LocalProcessSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[list[str]] = []
    original = sandbox._run

    def spy(argv: Any, **kwargs: Any) -> Any:
        recorded.append(list(argv))
        return original(argv, **kwargs)

    monkeypatch.setattr(sandbox, "_run", spy)
    sandbox.write("feature.txt", "x\n")
    sandbox.exec(["git", "add", "--", "."])
    sandbox.exec(["git", "commit", "-m", "feat: x"])
    sandbox.push("pam/ENG-1-feature", None)
    push_argv = next(argv for argv in recorded if argv[:2] == ["git", "push"])
    assert "--force" not in push_argv
    assert "-f" not in push_argv
    assert all(not arg.startswith("+") for arg in push_argv)
    with pytest.raises(SandboxError):
        sandbox.push("main", None)
    with pytest.raises(SandboxError):
        sandbox.push("release/2.0", None)


def test_timeout_kills_the_process_group_and_reports_124(
    sandbox: LocalProcessSandbox,
) -> None:
    start = time.monotonic()
    result = sandbox._run(
        ["sleep", "30"],
        cwd=sandbox._repo_dir,
        timeout_s=0.5,
        env=sandbox._base_env,
        capture_limit=1024,
    )
    assert result.timed_out is True
    assert result.exit_code == TIMEOUT_EXIT_CODE
    assert time.monotonic() - start < 15


def test_large_output_is_capped_with_a_marker(sandbox: LocalProcessSandbox) -> None:
    result = sandbox._run(
        ["head", "-c", "300000", "/dev/zero"],
        cwd=sandbox._repo_dir,
        timeout_s=10,
        env=sandbox._base_env,
        capture_limit=65536,
    )
    assert result.truncated is True
    assert "bytes truncated" in result.stdout
    assert len(result.stdout) < 70000


def test_destroy_runs_when_the_body_raises(tmp_path: Path, bare: Path) -> None:
    workspaces = tmp_path / "ws-error"
    with (
        pytest.raises(RuntimeError),
        LocalProcessSandbox(workspaces, allowed_schemes=("file",)) as sb,
    ):
        sb.clone(f"file://{bare}", "main", None)
        raise RuntimeError("boom")
    assert list(workspaces.iterdir()) == []


def test_destroy_is_idempotent_and_blocks_further_use(tmp_path: Path) -> None:
    sb = LocalProcessSandbox(tmp_path / "ws-twice")
    sb.destroy()
    sb.destroy()
    with pytest.raises(SandboxError):
        sb.exec(["git", "status"])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_child_environment_contains_no_host_secrets(
    tmp_path: Path, bare: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("LLM_API_KEY", "VCS_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, "fake-token-for-tests")
    node_dir = os.path.dirname(NODE or "")
    sb = LocalProcessSandbox(
        tmp_path / "ws-env",
        allowed_schemes=("file",),
        path_value=f"{node_dir}:{SAFE_PATH}",
        exec_env={"FEATURE_FLAG": "on"},
        git_identity=IDENTITY,
    )
    try:
        sb.clone(f"file://{bare}", "main", None)
        probe = Path(sb._repo_dir) / "probe.js"
        probe.write_text("console.log(JSON.stringify(process.env));\n")
        result = sb.exec(["node", "probe.js"], env_allowlist=["FEATURE_FLAG"])
        env = json.loads(result.stdout)
        assert "LLM_API_KEY" not in env
        assert "VCS_TOKEN" not in env
        assert "GITHUB_TOKEN" not in env
        assert env["FEATURE_FLAG"] == "on"
        assert env["GIT_AUTHOR_EMAIL"] == IDENTITY.email
        assert "fake-token-for-tests" not in result.stdout
    finally:
        sb.destroy()


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_node_eval_is_refused_and_npx_needs_a_local_binary(
    sandbox: LocalProcessSandbox,
) -> None:
    with pytest.raises(CommandNotAllowedError):
        sandbox.exec(["node", "-e", "1"])
    with pytest.raises(CommandNotAllowedError):
        sandbox.exec(["npx", "cowsay", "x"])


def test_credentials_flow_clones_and_pushes_over_authenticated_http(
    tmp_path: Path, bare: Path
) -> None:
    git_http = start_git_http(tmp_path / "served")
    served = tmp_path / "served" / "remote.git"
    served.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bare, served)
    run_git(["config", "http.receivepack", "true"], served)
    creds = GitCredentials(FAKE_USER, FAKE_TOKEN, git_http.host)
    sb = LocalProcessSandbox(
        tmp_path / "ws-http",
        allowed_schemes=("http",),
        git_identity=IDENTITY,
    )
    try:
        sb.clone(f"{git_http.base_url}/remote.git", "main", creds)
        assert git_http.server.auth_failures >= 1
        sb.write("pushed.txt", "from sandbox\n")
        sb.exec(["git", "add", "--", "."])
        sb.exec(["git", "commit", "-m", "feat: push over http"])
        sb.push("pam/ENG-2-http", creds)
        assert git_head_commit(served, "pam/ENG-2-http")

        config_text = (Path(sb._repo_dir) / ".git" / "config").read_text()
        assert FAKE_TOKEN not in config_text
        assert FAKE_USER not in config_text
        assert _token_free_tmp(sb._tmp_dir)
    finally:
        sb.destroy()
        git_http.stop()


def test_wrong_token_fails_without_leaking_it(tmp_path: Path, bare: Path) -> None:
    git_http = start_git_http(tmp_path / "served-bad", token="other-fake-token")
    served = tmp_path / "served-bad" / "remote.git"
    served.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bare, served)
    creds = GitCredentials(FAKE_USER, FAKE_TOKEN, git_http.host)
    sb = LocalProcessSandbox(tmp_path / "ws-bad", allowed_schemes=("http",))
    try:
        with pytest.raises(SandboxError) as info:
            sb.clone(f"{git_http.base_url}/remote.git", "main", creds)
        assert FAKE_TOKEN not in str(info.value)
        assert _token_free_tmp(sb._tmp_dir)
    finally:
        sb.destroy()
        git_http.stop()


def test_credentials_for_another_host_are_never_sent(
    tmp_path: Path, bare: Path
) -> None:
    creds = GitCredentials(FAKE_USER, FAKE_TOKEN, "git.example.test")
    sb = LocalProcessSandbox(tmp_path / "ws-host", allowed_schemes=("https", "file"))
    try:
        with pytest.raises(SandboxError):
            sb.clone(f"file://{bare}", "main", creds)
    finally:
        sb.destroy()


def _token_free_tmp(tmp_dir: str) -> bool:
    leftovers = [p for p in Path(tmp_dir).iterdir() if p.name.startswith("cred-")]
    return not leftovers and not any(
        FAKE_TOKEN in p.read_text(errors="ignore")
        for p in Path(tmp_dir).rglob("*")
        if p.is_file()
    )
