from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from code_squad._common.sandbox import (
    BudgetExceededError,
    LocalProcessSandbox,
    LoopDetectedError,
    MonitoredSandbox,
    TrajectoryMonitor,
)
from code_squad._common.sandbox.base import ExecResult
from code_squad._common.sandbox.env import GitIdentity
from tests.sandbox.support import FakeClock, make_bare_repo


def _result(
    argv: tuple[str, ...], exit_code: int, stdout: str = "", stderr: str = ""
) -> ExecResult:
    return ExecResult(
        argv=argv,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_s=0.25,
        truncated=False,
        timed_out=False,
    )


def test_same_failing_command_with_same_output_is_a_loop_at_three() -> None:
    monitor = TrajectoryMonitor(loop_threshold=3)
    failing = ("make", "test")
    monitor.record(_result(failing, 2, stderr="boom"))
    monitor.record(_result(failing, 2, stderr="boom"))
    with pytest.raises(LoopDetectedError):
        monitor.record(_result(failing, 2, stderr="boom"))


def test_changing_output_or_success_does_not_count_as_a_loop() -> None:
    monitor = TrajectoryMonitor(loop_threshold=3)
    monitor.record(_result(("make", "test"), 2, stderr="one"))
    monitor.record(_result(("make", "test"), 2, stderr="two"))
    monitor.record(_result(("make", "test"), 0, stdout="ok"))
    monitor.record(_result(("make", "test"), 0, stdout="ok"))
    monitor.record(_result(("make", "test"), 0, stdout="ok"))


def test_command_budget_stops_before_the_next_command() -> None:
    monitor = TrajectoryMonitor(max_commands=2)
    monitor.before_command()
    monitor.before_command()
    with pytest.raises(BudgetExceededError) as info:
        monitor.before_command()
    assert info.value.reason == "commands"


def test_wall_clock_budget_uses_the_injected_clock() -> None:
    clock = FakeClock()
    monitor = TrajectoryMonitor(max_wall_clock_s=10, clock=clock)
    monitor.check_budget()
    clock.advance(9.5)
    monitor.check_budget()
    clock.advance(1)
    with pytest.raises(BudgetExceededError) as info:
        monitor.check_budget()
    assert info.value.reason == "wall_clock"


def test_token_budget_is_enforced_per_call() -> None:
    monitor = TrajectoryMonitor()
    monitor.add_tokens(5, limit=10)
    monitor.add_tokens(5, limit=10)
    with pytest.raises(BudgetExceededError) as info:
        monitor.add_tokens(1, limit=10)
    assert info.value.reason == "tokens"


def test_audit_entries_hold_hashes_never_raw_output() -> None:
    monitor = TrajectoryMonitor()
    secret_looking = "customer-email: someone@example.test"
    monitor.record(_result(("git", "log"), 0, stdout=secret_looking))
    entry = monitor.audit_log()[0]
    assert set(entry) == {
        "argv",
        "exit_code",
        "duration_s",
        "output_sha256",
        "timed_out",
    }
    assert len(entry["output_sha256"]) == 16
    assert secret_looking not in json.dumps(monitor.audit_log())


@pytest.fixture
def monitored(tmp_path: Path) -> MonitoredSandbox:
    bare = make_bare_repo(tmp_path / "remote")
    inner = LocalProcessSandbox(
        tmp_path / "workspaces",
        allowed_schemes=("file",),
        git_identity=GitIdentity("Squad Bot", "squad-bot@example.test"),
    )
    inner.clone(f"file://{bare}", "main", None)
    return MonitoredSandbox(inner, TrajectoryMonitor(max_commands=2))


def test_monitored_sandbox_enforces_command_count_against_real_exec(
    monitored: MonitoredSandbox,
) -> None:
    with monitored:
        monitored.exec(["git", "status"])
        monitored.exec(["git", "status"])
        with pytest.raises(BudgetExceededError):
            monitored.exec(["git", "status"])


def test_denied_commands_count_against_budget_and_loop_detection(
    tmp_path: Path,
) -> None:
    bare = make_bare_repo(tmp_path / "remote")
    inner = LocalProcessSandbox(tmp_path / "ws-denied", allowed_schemes=("file",))
    inner.clone(f"file://{bare}", "main", None)
    monitored = MonitoredSandbox(inner, TrajectoryMonitor(loop_threshold=3))
    with monitored:
        from code_squad._common.sandbox import CommandNotAllowedError

        for _ in range(2):
            with pytest.raises(CommandNotAllowedError):
                monitored.exec(["sh", "-c", "id"])
        with pytest.raises(LoopDetectedError):
            monitored.exec(["sh", "-c", "id"])


def test_monitored_exec_logs_metadata_only(
    monitored: MonitoredSandbox, caplog: pytest.LogCaptureFixture
) -> None:
    with monitored, caplog.at_level(logging.INFO, logger="code_squad.sandbox"):
        monitored.exec(["git", "status"])
    records = [r for r in caplog.records if r.getMessage() == "sandbox command"]
    assert records
    record = records[-1]
    assert record.tool == "git"  # type: ignore[attr-defined]
    assert record.status == "ok"  # type: ignore[attr-defined]
    assert not hasattr(record, "stdout")
