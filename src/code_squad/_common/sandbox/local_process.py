from __future__ import annotations

import functools
import os
import posixpath
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Final

from code_squad._common.sandbox.base import (
    TIMEOUT_EXIT_CODE,
    BaseSandbox,
    ExecResult,
)
from code_squad._common.sandbox.env import SAFE_PATH, GitIdentity
from code_squad._common.sandbox.errors import SandboxError
from code_squad._common.sandbox.output import capture_file

_CPU_GRACE_S: Final = 5
_FILE_SIZE_LIMIT: Final = 512 * 1024 * 1024


class LocalProcessSandbox(BaseSandbox):
    """Development and test backend: host temp workspace, no container isolation."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        allowed_extra: Iterable[str] = (),
        max_output: int = 65536,
        *,
        path_value: str = SAFE_PATH,
        allowed_schemes: Sequence[str] = ("https",),
        protected_branches: Sequence[str] = (
            "main",
            "master",
            "develop",
            "release/*",
        ),
        exec_env: Mapping[str, str] | None = None,
        git_identity: GitIdentity | None = None,
    ) -> None:
        parent = None if workspace_root is None else str(workspace_root)
        if parent is not None:
            os.makedirs(parent, exist_ok=True)
        self._root = tempfile.mkdtemp(prefix="squad-sandbox-", dir=parent)
        os.chmod(self._root, 0o700)
        self._repo = posixpath.join(self._root, "repo")
        self._home = posixpath.join(self._root, ".home")
        self._tmp = posixpath.join(self._root, ".tmp")
        try:
            os.makedirs(self._home, mode=0o700)
            os.makedirs(self._tmp, mode=0o700)
            super().__init__(
                path_value=path_value,
                allowed_extra=allowed_extra,
                allowed_schemes=allowed_schemes,
                protected_branches=protected_branches,
                exec_env=exec_env,
                git_identity=git_identity,
                max_output=max_output,
            )
        except BaseException:
            shutil.rmtree(self._root, ignore_errors=True)
            raise

    @property
    def _root_dir(self) -> str:
        return self._root

    @property
    def _repo_dir(self) -> str:
        return self._repo

    @property
    def _home_dir(self) -> str:
        return self._home

    @property
    def _tmp_dir(self) -> str:
        return self._tmp

    def _local_bin_dir(self) -> str | None:
        return posixpath.join(self._repo, "node_modules", ".bin")

    def _run(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        timeout_s: float,
        env: Mapping[str, str],
        capture_limit: int,
    ) -> ExecResult:
        exe = shutil.which(argv[0], path=env.get("PATH", SAFE_PATH))
        if exe is None:
            raise SandboxError(f"executable not found in sandbox PATH: {argv[0]}")
        preexec = None
        if sys.platform == "linux":
            preexec = functools.partial(_limit_child, int(timeout_s) + _CPU_GRACE_S)
        start = time.monotonic()
        with (
            tempfile.TemporaryFile(dir=self._tmp) as out,
            tempfile.TemporaryFile(dir=self._tmp) as err,
        ):
            proc = subprocess.Popen(
                list(argv),
                executable=exe,
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=True,
                preexec_fn=preexec,
            )
            timed_out = False
            try:
                code = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_group(proc.pid)
                code = proc.wait()
            _kill_group(proc.pid)
            stdout, out_cut = capture_file(out, capture_limit)
            stderr, err_cut = capture_file(err, capture_limit)
        return ExecResult(
            argv=tuple(argv),
            exit_code=TIMEOUT_EXIT_CODE if timed_out else code,
            stdout=stdout,
            stderr=stderr,
            duration_s=time.monotonic() - start,
            truncated=out_cut or err_cut,
            timed_out=timed_out,
        )

    def _put_file(self, path: str, data: bytes, mode: int) -> None:
        try:
            fd = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                mode,
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.chmod(path, mode)
        except OSError as exc:
            raise SandboxError(f"cannot write sandbox file: {exc.strerror}") from exc

    def _get_file(self, path: str, limit: int) -> str:
        try:
            with open(path, "rb") as handle:
                data = handle.read(limit + 1)
        except OSError as exc:
            raise SandboxError(f"cannot read sandbox file: {exc.strerror}") from exc
        if len(data) > limit:
            raise SandboxError("file exceeds the read limit")
        return data.decode("utf-8", "replace")

    def _resolve(self, path: str) -> str:
        return os.path.realpath(path)

    def _mkdirs(self, path: str) -> None:
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            raise SandboxError(f"cannot create directory: {exc.strerror}") from exc

    def _make_private_dir(self, path: str) -> None:
        try:
            os.makedirs(path, mode=0o700)
        except OSError as exc:
            raise SandboxError(
                f"cannot create private directory: {exc.strerror}"
            ) from exc

    def _remove(self, path: str, *, recursive: bool) -> None:
        try:
            if recursive:
                shutil.rmtree(path)
            else:
                os.unlink(path)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise SandboxError(f"cannot remove sandbox path: {exc.strerror}") from exc

    def _destroy_backend(self) -> None:
        shutil.rmtree(self._root, ignore_errors=True)


def _limit_child(cpu_seconds: int) -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_FILE_SIZE_LIMIT, _FILE_SIZE_LIMIT))


def _kill_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return
