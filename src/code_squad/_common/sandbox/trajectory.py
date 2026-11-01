from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Final, Self

from code_squad._common.sandbox.base import (
    DEFAULT_TIMEOUT_S,
    POLICY_DENIED_EXIT_CODE,
    ExecResult,
    Sandbox,
)
from code_squad._common.sandbox.credentials import GitCredentials
from code_squad._common.sandbox.errors import (
    BudgetExceededError,
    CommandNotAllowedError,
    LoopDetectedError,
    PathEscapeError,
)

_logger = logging.getLogger("code_squad.sandbox")
_DIGEST_CHARS: Final = 16


@dataclass(frozen=True)
class AuditEntry:
    argv: tuple[str, ...]
    exit_code: int
    duration_s: float
    output_sha256: str
    timed_out: bool


class TrajectoryMonitor:
    def __init__(
        self,
        *,
        max_commands: int = 60,
        max_wall_clock_s: float = 1800.0,
        loop_threshold: int = 3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_commands < 1 or max_wall_clock_s <= 0 or loop_threshold < 2:
            raise ValueError("invalid trajectory budget")
        self._max_commands = max_commands
        self._max_wall_clock_s = max_wall_clock_s
        self._loop_threshold = loop_threshold
        self._clock = clock
        self._started = clock()
        self._attempts = 0
        self._tokens = 0
        self._entries: list[AuditEntry] = []

    @property
    def tokens(self) -> int:
        return self._tokens

    def check_budget(self) -> None:
        if self._attempts >= self._max_commands:
            raise BudgetExceededError("commands")
        if self._clock() - self._started >= self._max_wall_clock_s:
            raise BudgetExceededError("wall_clock")

    def before_command(self) -> None:
        self.check_budget()
        self._attempts += 1

    def add_tokens(self, n: int, limit: int) -> None:
        if n < 0:
            raise ValueError("token count must not be negative")
        self._tokens += n
        if self._tokens > limit:
            raise BudgetExceededError("tokens")

    def record(self, result: ExecResult) -> None:
        output = (result.stdout + result.stderr).encode("utf-8")
        self._store(
            AuditEntry(
                argv=result.argv,
                exit_code=result.exit_code,
                duration_s=result.duration_s,
                output_sha256=_digest(output),
                timed_out=result.timed_out,
            )
        )

    def record_operation(
        self,
        argv: tuple[str, ...],
        *,
        exit_code: int,
        duration_s: float,
        output: str = "",
    ) -> None:
        self._store(
            AuditEntry(
                argv=argv,
                exit_code=exit_code,
                duration_s=duration_s,
                output_sha256=_digest(output.encode("utf-8")),
                timed_out=False,
            )
        )

    def audit_log(self) -> list[dict[str, Any]]:
        return [
            {
                "argv": list(entry.argv),
                "exit_code": entry.exit_code,
                "duration_s": round(entry.duration_s, 3),
                "output_sha256": entry.output_sha256,
                "timed_out": entry.timed_out,
            }
            for entry in self._entries
        ]

    def _store(self, entry: AuditEntry) -> None:
        self._entries.append(entry)
        if entry.exit_code == 0:
            return
        repeats = sum(1 for other in self._entries if _same_failure(other, entry))
        if repeats >= self._loop_threshold:
            raise LoopDetectedError(
                f"same failing command repeated {repeats} times: {entry.argv[:2]}"
            )


class MonitoredSandbox:
    """Wraps a Sandbox with budgets, loop detection, audit and metadata-only logs."""

    def __init__(self, inner: Sandbox, monitor: TrajectoryMonitor) -> None:
        self._inner = inner
        self._monitor = monitor

    def clone(
        self, repo_url: str, ref: str, credentials: GitCredentials | None
    ) -> None:
        argv = ("git", "clone", ref)
        self._counted(argv, lambda: self._inner.clone(repo_url, ref, credentials))

    def exec(
        self,
        argv: Sequence[str],
        timeout_s: float = DEFAULT_TIMEOUT_S,
        env_allowlist: Sequence[str] = (),
    ) -> ExecResult:
        self._monitor.before_command()
        try:
            result = self._inner.exec(argv, timeout_s, env_allowlist)
        except CommandNotAllowedError as exc:
            self._denied(tuple(str(item) for item in argv), exc)
            raise
        self._monitor.record(result)
        _log_command(result.argv, _status(result), result.duration_s)
        return result

    def read(self, path: str) -> str:
        self._monitor.check_budget()
        return self._inner.read(path)

    def write(self, path: str, content: str) -> None:
        self._monitor.check_budget()
        self._inner.write(path, content)

    def apply_patch(self, patch: str) -> ExecResult:
        self._monitor.before_command()
        argv = ("git", "apply")
        try:
            result = self._inner.apply_patch(patch)
        except PathEscapeError as exc:
            self._denied(argv, exc)
            raise
        self._monitor.record(result)
        _log_command(result.argv, _status(result), result.duration_s)
        return result

    def diff(self) -> str:
        argv = ("git", "diff")
        return self._counted_value(argv, self._inner.diff)

    def push(self, branch: str, credentials: GitCredentials | None) -> None:
        argv = ("git", "push", branch)
        self._counted(argv, lambda: self._inner.push(branch, credentials))

    def destroy(self) -> None:
        self._inner.destroy()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.destroy()

    def _counted(self, argv: tuple[str, ...], operation: Callable[[], None]) -> None:
        def run() -> str:
            operation()
            return ""

        self._counted_value(argv, run)

    def _counted_value(
        self, argv: tuple[str, ...], operation: Callable[[], str]
    ) -> str:
        self._monitor.before_command()
        start = time.monotonic()
        try:
            value = operation()
        except Exception as exc:
            elapsed = time.monotonic() - start
            self._monitor.record_operation(
                argv, exit_code=1, duration_s=elapsed, output=str(exc)
            )
            _log_command(argv, "failed", elapsed)
            raise
        elapsed = time.monotonic() - start
        self._monitor.record_operation(
            argv, exit_code=0, duration_s=elapsed, output=value
        )
        _log_command(argv, "ok", elapsed)
        return value

    def _denied(self, argv: tuple[str, ...], exc: Exception) -> None:
        self._monitor.record_operation(
            argv, exit_code=POLICY_DENIED_EXIT_CODE, duration_s=0.0, output=str(exc)
        )
        _log_command(argv, "denied", 0.0)


def _same_failure(left: AuditEntry, right: AuditEntry) -> bool:
    return (
        left.argv == right.argv
        and left.exit_code == right.exit_code
        and left.output_sha256 == right.output_sha256
    )


def _status(result: ExecResult) -> str:
    if result.timed_out:
        return "timeout"
    return "ok" if result.exit_code == 0 else "failed"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:_DIGEST_CHARS]


def _log_command(argv: tuple[str, ...], status: str, duration_s: float) -> None:
    _logger.info(
        "sandbox command",
        extra={
            "tool": argv[0] if argv else "",
            "status": status,
            "duration_ms": int(duration_s * 1000),
        },
    )
