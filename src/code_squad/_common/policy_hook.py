from __future__ import annotations

from typing import Any, Final

from strands.hooks import (
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

from code_squad._common.context import InvocationContext, current
from code_squad._common.observability import DRY_RUN
from code_squad._common.posting import DryRunError
from code_squad._common.tool_policy import ToolClass, UnclassifiedToolError, classify

TOOL_BUDGET_REASON: Final = (
    "tool-call budget exhausted: the run stopped before finish(); result is incomplete"
)


class ToolPolicyHook(HookProvider):
    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, _enforce_policy)


class IterationCounterHook(HookProvider):
    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, _count_iteration)


def _enforce_policy(event: BeforeToolCallEvent) -> None:
    name = str(event.tool_use["name"])
    ctx = current()
    if _over_tool_budget(ctx):
        if ctx.budget_stop is None:
            ctx.budget_stop = TOOL_BUDGET_REASON
        event.cancel_tool = "tool-call budget exhausted; tool not run"
        event.agent.cancel()
        return
    try:
        policy = classify(name)
    except UnclassifiedToolError:
        event.cancel_tool = f"tool '{name}' is not classified; refused"
        return
    ctx.tool_calls[name] += 1
    if policy is ToolClass.EXTERNAL_WRITE:
        try:
            ctx.gate.require_write(name)
        except DryRunError as exc:
            DRY_RUN.labels(agent=ctx.agent).inc()
            event.cancel_tool = str(exc)


def _over_tool_budget(ctx: InvocationContext) -> bool:
    budget = ctx.tool_call_budget
    return budget is not None and sum(ctx.tool_calls.values()) >= budget


def _count_iteration(event: BeforeModelCallEvent) -> None:
    current().iterations += 1
