from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class OperationJournal(Protocol):
    def lookup(self, key: str, op_id: str) -> str | None: ...

    def record(self, key: str, op_id: str, value: str) -> None: ...


class MemoryJournal:
    """In-process journal. Sessions reuse the same protocol over the session store."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], str] = {}

    def lookup(self, key: str, op_id: str) -> str | None:
        return self._entries.get((key, op_id))

    def record(self, key: str, op_id: str, value: str) -> None:
        self._entries.setdefault((key, op_id), value)


def run_once(
    journal: OperationJournal,
    key: str,
    op_id: str,
    fn: Callable[[], str],
) -> tuple[str, bool]:
    """Run ``fn`` unless ``(key, op_id)`` already completed; returns (value, executed).

    A failing ``fn`` records nothing, so a later attempt may run it again.
    """
    recorded = journal.lookup(key, op_id)
    if recorded is not None:
        return recorded, False
    value = fn()
    journal.record(key, op_id, value)
    return value, True
