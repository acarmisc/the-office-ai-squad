from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from code_squad._common.contract import FinishPayload, InvocationRequest
from code_squad._common.posting import PostingGate


@dataclass
class InvocationContext:
    agent: str
    request: InvocationRequest
    gate: PostingGate
    finish_result: FinishPayload | None = None
    tool_calls: Counter[str] = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)
    services: dict[str, Any] = field(default_factory=dict)
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    invalid_finish_attempts: int = 0
    tool_call_budget: int | None = None
    max_run_tokens: int | None = None
    budget_stop: str | None = None


_CURRENT: ContextVar[InvocationContext | None] = ContextVar(
    "squad_invocation", default=None
)


def current() -> InvocationContext:
    ctx = _CURRENT.get()
    if ctx is None:
        raise RuntimeError("no invocation context is active")
    return ctx


@contextmanager
def use_context(ctx: InvocationContext) -> Iterator[InvocationContext]:
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)
