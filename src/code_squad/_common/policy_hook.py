from __future__ import annotations

from typing import Any

from strands.hooks import (
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

from code_squad._common.context import current
from code_squad._common.observability import DRY_RUN
from code_squad._common.posting import DryRunError
from code_squad._common.tool_policy import ToolClass, UnclassifiedToolError, classify


class ToolPolicyHook(HookProvider):
    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, _enforce_policy)


class IterationCounterHook(HookProvider):
    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, _count_iteration)


def _enforce_policy(event: BeforeToolCallEvent) -> None:
    name = str(event.tool_use["name"])
    try:
        policy = classify(name)
    except UnclassifiedToolError:
        event.cancel_tool = f"tool '{name}' is not classified; refused"
        return
    ctx = current()
    ctx.tool_calls[name] += 1
    if policy is ToolClass.EXTERNAL_WRITE:
        try:
            ctx.gate.require_write(name)
        except DryRunError as exc:
            DRY_RUN.labels(agent=ctx.agent).inc()
            event.cancel_tool = str(exc)


def _count_iteration(event: BeforeModelCallEvent) -> None:
    current().iterations += 1
