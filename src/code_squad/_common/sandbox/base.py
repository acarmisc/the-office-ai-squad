from __future__ import annotations

import contextlib
import math
import posixpath
import secrets
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import TracebackType
from typing import Final, Protocol, Self

from code_squad._common.sandbox.credentials import (
    ASKPASS_SCRIPT,
    GitCredentials,
    askpass_environment,
    check_credentials_for_url,
    token_file_content,
)
from code_squad._common.sandbox.env import (
    SAFE_PATH,
    GitIdentity,
    env_from_allowlist,
    scrubbed_env,
    validate_env_name,
)
from code_squad._common.sandbox.errors import SandboxError
from code_squad._common.sandbox.output import redact_secrets
from code_squad._common.sandbox.policy import (
    DEFAULT_PROTECTED_BRANCHES,
    allowed_executables,
    check_relpath,
    validate_argv,
    validate_branch,
    validate_patch,
    validate_ref,
    validate_repo_url,
)

MAX_READ_BYTES: Final = 1_048_576
MAX_WRITE_BYTES: Final = 4_194_304
MAX_PATCH_BYTES: Final = 1_048_576
DIFF_CAPTURE_BYTES: Final = 8_388_608
DEFAULT_TIMEOUT_S: Final = 300.0
MAX_TIMEOUT_S: Final = 3600.0
GIT_TIMEOUT_S: Final = 600.0
SMALL_OP_TIMEOUT_S: Final = 60.0
CLONE_DEPTH: Final = 50
TIMEOUT_EXIT_CODE: Final = 124
POLICY_DENIED_EXIT_CODE: Final = -2
_ALLOWED_SCHEMES: Final = frozenset({"https", "http", "file"})


@dataclass(frozen=True)
class ExecResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    truncated: bool
    timed_out: bool


class Sandbox(Protocol):
    def clone(
        self, repo_url: str, ref: str, credentials: GitCredentials | None
    ) -> None: ...

    def exec(
        self,
        argv: Sequence[str],
        timeout_s: float = DEFAULT_TIMEOUT_S,
        env_allowlist: Sequence[str] = (),
    ) -> ExecResult: ...

    def read(self, path: str) -> str: ...

    def write(self, path: str, content: str) -> None: ...

    def apply_patch(self, patch: str) -> ExecResult: ...

    def diff(self) -> str: ...

    def push(self, branch: str, credentials: GitCredentials | None) -> None: ...

    def destroy(self) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


@dataclass(frozen=True)
class _Remote:
    url: str


class BaseSandbox(ABC):
    """Shared policy, credential and patch logic. Backends provide only primitives."""

    def __init__(
        self,
        *,
        path_value: str = SAFE_PATH,
        allowed_extra: Iterable[str] = (),
        allowed_schemes: Sequence[str] = ("https",),
        protected_branches: Sequence[str] = DEFAULT_PROTECTED_BRANCHES,
        exec_env: Mapping[str, str] | None = None,
        git_identity: GitIdentity | None = None,
        max_output: int = 65536,
    ) -> None:
        if not 1024 <= max_output <= 1_048_576:
            raise ValueError("max_output must be between 1 KiB and 1 MiB")
        schemes = tuple(scheme.lower() for scheme in allowed_schemes)
        if not schemes or not set(schemes) <= _ALLOWED_SCHEMES:
            raise ValueError(
                "allowed_schemes must be a non-empty subset of https/http/file"
            )
        self._allowed = allowed_executables(allowed_extra)
        self._schemes = schemes
        self._protected = tuple(protected_branches)
        self._exec_env = dict(exec_env or {})
        self._max_output = max_output
        self._remote: _Remote | None = None
        self._destroyed = False
        self._base_env = scrubbed_env(
            home=self._home_dir,
            tmp=self._tmp_dir,
            path=path_value,
            allowed_schemes=schemes,
            identity=git_identity,
        )

    @property
    @abstractmethod
    def _root_dir(self) -> str: ...

    @property
    @abstractmethod
    def _repo_dir(self) -> str: ...

    @property
    @abstractmethod
    def _home_dir(self) -> str: ...

    @property
    @abstractmethod
    def _tmp_dir(self) -> str: ...

    @abstractmethod
    def _run(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        timeout_s: float,
        env: Mapping[str, str],
        capture_limit: int,
    ) -> ExecResult: ...

    @abstractmethod
    def _put_file(self, path: str, data: bytes, mode: int) -> None: ...

    @abstractmethod
    def _get_file(self, path: str, limit: int) -> str: ...

    @abstractmethod
    def _resolve(self, path: str) -> str: ...

    @abstractmethod
    def _mkdirs(self, path: str) -> None: ...

    @abstractmethod
    def _make_private_dir(self, path: str) -> None: ...

    @abstractmethod
    def _remove(self, path: str, *, recursive: bool) -> None: ...

    @abstractmethod
    def _destroy_backend(self) -> None: ...

    def _local_bin_dir(self) -> str | None:
        return None

    def clone(
        self, repo_url: str, ref: str, credentials: GitCredentials | None
    ) -> None:
        self._require_live()
        if self._remote is not None:
            raise SandboxError("a repository is already cloned into this sandbox")
        url = validate_repo_url(repo_url, self._schemes)
        validate_ref(ref)
        if credentials is not None:
            check_credentials_for_url(credentials, url, self._schemes)
        argv = [
            "git",
            "clone",
            "--no-tags",
            "--depth",
            str(CLONE_DEPTH),
            "--branch",
            ref,
            "--",
            url,
            self._repo_dir,
        ]
        self._git(
            argv,
            cwd=self._root_dir,
            what="git clone",
            credentials=credentials,
        )
        self._remote = _Remote(url=url)

    def exec(
        self,
        argv: Sequence[str],
        timeout_s: float = DEFAULT_TIMEOUT_S,
        env_allowlist: Sequence[str] = (),
    ) -> ExecResult:
        self._require_live()
        checked = validate_argv(
            argv, self._allowed, local_bin_dir=self._local_bin_dir()
        )
        env = self._compose_env(env_allowlist)
        return self._run(
            checked,
            cwd=self._repo_dir,
            timeout_s=_check_timeout(timeout_s),
            env=env,
            capture_limit=self._max_output,
        )

    def read(self, path: str) -> str:
        self._require_live()
        target = self._safe_repo_path(path, write=False)
        return self._get_file(target, MAX_READ_BYTES)

    def write(self, path: str, content: str) -> None:
        self._require_live()
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise SandboxError("content exceeds the write limit")
        target = self._safe_repo_path(path, write=True)
        self._mkdirs(posixpath.dirname(target))
        self._put_file(target, data, 0o644)

    def apply_patch(self, patch: str) -> ExecResult:
        self._require_live()
        validate_patch(patch)
        data = patch.encode("utf-8")
        if len(data) > MAX_PATCH_BYTES:
            raise SandboxError("patch exceeds the size limit")
        path = posixpath.join(self._tmp_dir, f"patch-{secrets.token_hex(8)}.diff")
        self._put_file(path, data, 0o600)
        try:
            return self._run(
                ["git", "apply", "--whitespace=nowarn", path],
                cwd=self._repo_dir,
                timeout_s=GIT_TIMEOUT_S,
                env=self._base_env,
                capture_limit=self._max_output,
            )
        finally:
            self._remove_quietly(path, recursive=False)

    def diff(self) -> str:
        self._require_live()
        self._git(
            ["git", "add", "--intent-to-add", "--all"],
            cwd=self._repo_dir,
            what="git add",
        )
        result = self._run(
            ["git", "diff", "--no-color", "--no-ext-diff", "--no-textconv", "HEAD"],
            cwd=self._repo_dir,
            timeout_s=GIT_TIMEOUT_S,
            env=self._base_env,
            capture_limit=DIFF_CAPTURE_BYTES,
        )
        if result.truncated or result.timed_out or result.exit_code != 0:
            raise SandboxError("git diff failed or exceeded the capture limit")
        return result.stdout

    def push(self, branch: str, credentials: GitCredentials | None) -> None:
        self._require_live()
        if self._remote is None:
            raise SandboxError("nothing is cloned in this sandbox")
        validate_branch(branch, self._protected)
        if credentials is not None:
            check_credentials_for_url(credentials, self._remote.url, self._schemes)
        self._git(
            ["git", "push", "origin", f"HEAD:refs/heads/{branch}"],
            cwd=self._repo_dir,
            what="git push",
            credentials=credentials,
        )

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroy_backend()
        self._destroyed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.destroy()

    def _require_live(self) -> None:
        if self._destroyed:
            raise SandboxError("sandbox has been destroyed")

    def _compose_env(self, names: Sequence[str]) -> dict[str, str]:
        for name in names:
            validate_env_name(name)
        return env_from_allowlist(names, self._exec_env, self._base_env)

    def _git(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        what: str,
        credentials: GitCredentials | None = None,
        timeout_s: float = GIT_TIMEOUT_S,
    ) -> ExecResult:
        if credentials is None:
            result = self._run(
                argv,
                cwd=cwd,
                timeout_s=timeout_s,
                env=self._base_env,
                capture_limit=self._max_output,
            )
        else:
            result = self._run_with_credentials(
                argv, cwd=cwd, timeout_s=timeout_s, credentials=credentials
            )
        if result.timed_out or result.exit_code != 0:
            tail = result.stderr[-500:]
            raise SandboxError(f"{what} failed (exit {result.exit_code}): {tail}")
        return result

    def _run_with_credentials(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        timeout_s: float,
        credentials: GitCredentials,
    ) -> ExecResult:
        cred_dir = posixpath.join(self._tmp_dir, f"cred-{secrets.token_hex(8)}")
        askpass = posixpath.join(cred_dir, "askpass.sh")
        token_file = posixpath.join(cred_dir, "token")
        try:
            self._make_private_dir(cred_dir)
            self._put_file(askpass, ASKPASS_SCRIPT.encode(), 0o700)
            self._put_file(token_file, token_file_content(credentials.token), 0o600)
            env = {
                **self._base_env,
                **askpass_environment(credentials, askpass, token_file),
            }
            result = self._run(
                argv,
                cwd=cwd,
                timeout_s=timeout_s,
                env=env,
                capture_limit=self._max_output,
            )
        finally:
            self._remove_quietly(cred_dir, recursive=True)
        secrets_seen = [credentials.token]
        return replace(
            result,
            stdout=redact_secrets(result.stdout, secrets_seen),
            stderr=redact_secrets(result.stderr, secrets_seen),
        )

    def _safe_repo_path(self, rel: str, *, write: bool) -> str:
        check_relpath(rel, allow_git=not write)
        root = self._resolve(self._repo_dir)
        target = self._resolve(posixpath.join(self._repo_dir, rel))
        if target != root and not target.startswith(root + "/"):
            raise SandboxError(f"path escapes the repository: {rel!r}")
        inside = target[len(root) :].split("/")
        if write and any(part.lower() == ".git" for part in inside):
            raise SandboxError(f"writes into .git are not allowed: {rel!r}")
        return target

    def _remove_quietly(self, path: str, *, recursive: bool) -> None:
        with contextlib.suppress(SandboxError):
            self._remove(path, recursive=recursive)


def _check_timeout(timeout_s: float) -> float:
    if not math.isfinite(timeout_s) or not 0 < timeout_s <= MAX_TIMEOUT_S:
        raise ValueError(f"timeout must be in (0, {MAX_TIMEOUT_S}] seconds")
    return timeout_s
