from __future__ import annotations

import pytest

from code_squad._common.safe_retry import MemoryJournal, run_once


def test_journal_returns_recorded_value_per_key_and_op() -> None:
    journal = MemoryJournal()
    assert journal.lookup("k", "publish") is None
    journal.record("k", "publish", "done")
    assert journal.lookup("k", "publish") == "done"
    assert journal.lookup("k", "other-op") is None
    assert journal.lookup("other-key", "publish") is None


def test_run_once_executes_the_operation_only_once() -> None:
    journal = MemoryJournal()
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        return "posted:2"

    first = run_once(journal, "key-1", "publish", operation)
    second = run_once(journal, "key-1", "publish", operation)
    assert first == ("posted:2", True)
    assert second == ("posted:2", False)
    assert len(calls) == 1


def test_failed_operation_is_not_recorded_so_a_retry_runs_it_again() -> None:
    journal = MemoryJournal()
    attempts: list[int] = []

    def flaky() -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("transient")
        return "ok"

    with pytest.raises(RuntimeError):
        run_once(journal, "key", "publish", flaky)
    assert run_once(journal, "key", "publish", flaky) == ("ok", True)
    assert len(attempts) == 2


def test_different_keys_do_not_share_results() -> None:
    journal = MemoryJournal()
    assert run_once(journal, "a", "op", lambda: "1") == ("1", True)
    assert run_once(journal, "b", "op", lambda: "2") == ("2", True)
