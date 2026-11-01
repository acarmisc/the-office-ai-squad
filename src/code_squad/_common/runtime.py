from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from typing import Any, Final

import openai
from strands import Agent
from strands.models.model import Model
from strands.types.agent import Limits
from strands.types.event_loop import StopReason
from strands.types.exceptions import MaxTokensReachedException, ModelThrottledException

from code_squad._common.common_tools import MAX_INVALID_FINISH
from code_squad._common.context import InvocationContext, current, use_context
from code_squad._common.contract import (
    Finding,
    InvocationRequest,
    InvocationResult,
    RunStatus,
    Stats,
    Verdict,
)
from code_squad._common.model import (
    ModelFactory,
    dropped_caller_tags,
    get_model_factory,
    litellm_tags,
)
from code_squad._common.policy_hook import IterationCounterHook, ToolPolicyHook
from code_squad._common.posting import PostingGate
from code_squad._common.skills.loader import skillset_from_payload
from code_squad._common.skills.tools import (
    applied_skills,
    skills_prompt_section,
    skillset_from_services,
)
from code_squad._common.spec import AgentSpec
from code_squad._common.untrusted import UNTRUSTED_RULE

_TRUNCATED: Final = (
    "Your previous answer was truncated at the token limit. "
    "Produce a SHORTER answer with the same shape and call finish()."
)
_MISSING_FINISH: Final = (
    "You stopped without calling finish(). Call finish() now with valid arguments: "
    "verdict, summary and findings (may be empty)."
)
_INCOMPLETE_SUMMARY: Final = (
    "Run incomplete: no finish() result was produced. This is not a clean result."
)
_FAILED_SUMMARY: Final = "Run failed before a result was produced."
DEFAULT_MAX_RUN_TOKENS: Final = 400_000
FALLBACK_WARNING: Final = (
    "fallback model used after the primary model was overloaded; "
    "the run was retried once"
)
WALL_CLOCK_REASON: Final = (
    "wall-clock budget exceeded: the run was cancelled; result is incomplete"
)
TOKEN_CEILING_REASON: Final = (
    "token ceiling reached (limits.max_run_tokens): result is incomplete"
)
_NO_RETRY_STOPS: Final = frozenset({"limit_turns", "limit_total_tokens", "cancelled"})


def create_agent(
    spec: AgentSpec,
    model: Model,
    tools_override: Sequence[Any] | None = None,
) -> Agent:
    gate = current().gate
    tools = list(tools_override) if tools_override is not None else list(spec.tools)
    system_prompt = "\n\n".join(
        [spec.system_prompt, UNTRUSTED_RULE, _dry_run_note(gate), *_skill_sections()]
    )
    return Agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        callback_handler=None,
        name=spec.name,
        hooks=[ToolPolicyHook(), IterationCounterHook()],
    )


def run_task(
    spec: AgentSpec,
    request: InvocationRequest,
    *,
    services: dict[str, Any] | None = None,
    model_factory: ModelFactory | None = None,
    post_override: bool | None = None,
) -> InvocationResult:
    merged = _services_with_skills(services, request, spec.name)
    ctx = InvocationContext(
        agent=spec.name,
        request=request,
        gate=_gate(request, post_override),
        services=merged,
        tool_call_budget=_agent_budget(merged, spec.name, "tool_calls"),
        max_run_tokens=_token_ceiling(merged, spec.name),
    )
    clock = _WallClock(_agent_budget(merged, spec.name, "wall_clock_seconds"), ctx)
    factory = model_factory or get_model_factory()
    with use_context(ctx):
        clock.start()
        try:
            return _run(spec, request, ctx, factory, clock)
        except Exception as exc:
            ctx.warnings.append(f"model call failed: {type(exc).__name__}")
            return _result(
                spec, ctx, RunStatus.FAILED, Verdict.INCOMPLETE, _FAILED_SUMMARY
            )
        finally:
            clock.stop()


class _WallClock:
    """Cancels the running agent when the wall-clock budget expires."""

    def __init__(self, seconds: int | None, ctx: InvocationContext) -> None:
        self._ctx = ctx
        self._lock = threading.Lock()
        self._agent: Agent | None = None
        self._timer: threading.Timer | None = None
        if seconds is not None:
            self._timer = threading.Timer(float(seconds), self._expire)
            self._timer.daemon = True

    def start(self) -> None:
        if self._timer is not None:
            self._timer.start()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()

    def bind(self, agent: Agent) -> None:
        with self._lock:
            self._agent = agent
            if self._ctx.budget_stop is not None:
                agent.cancel()

    def unbind(self) -> None:
        with self._lock:
            self._agent = None

    def _expire(self) -> None:
        with self._lock:
            if self._ctx.budget_stop is None:
                self._ctx.budget_stop = WALL_CLOCK_REASON
            if self._agent is not None:
                self._agent.cancel()


def _config(services: Mapping[str, Any] | None) -> Any:
    if services is None:
        return None
    return getattr(services.get("config"), "config", None)


def _agent_budget(
    services: Mapping[str, Any] | None, agent: str, field: str
) -> int | None:
    agents = getattr(_config(services), "agents", None)
    if not isinstance(agents, Mapping):
        return None
    budgets = getattr(agents.get(agent), "budgets", None)
    return _positive(getattr(budgets, field, None))


def _token_ceiling(services: Mapping[str, Any] | None, agent: str) -> int:
    limits = getattr(_config(services), "limits", None)
    ceiling = _positive(getattr(limits, "max_run_tokens", None)) or (
        DEFAULT_MAX_RUN_TOKENS
    )
    per_agent = _agent_budget(services, agent, "tokens")
    return min(ceiling, per_agent) if per_agent is not None else ceiling


def _positive(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _is_overload(exc: BaseException) -> bool:
    """Gateway throttling or a server error: the only failures a fallback retries."""
    if isinstance(exc, ModelThrottledException):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _gate(request: InvocationRequest, post_override: bool | None) -> PostingGate:
    if post_override is False:
        return PostingGate(post_allowed=False)
    return PostingGate.from_request(request)


def _run(
    spec: AgentSpec,
    request: InvocationRequest,
    ctx: InvocationContext,
    factory: ModelFactory,
    clock: _WallClock,
) -> InvocationResult:
    model_id = request.model or spec.model_id
    tags = litellm_tags(spec.name, request.project, request.litellm_tags)
    ctx.warnings.extend(_tag_warnings(request.litellm_tags))
    prompt = _task_prompt(spec, request)
    stop = _first_attempt(spec, ctx, factory, model_id, tags, prompt, clock)
    instruction = _retry_instruction(stop, ctx)
    if instruction is not None:
        retry_id = (
            spec.retry_model_id
            if stop == "max_tokens" and spec.retry_model_id
            else model_id
        )
        retry_model = factory(retry_id, spec.max_tokens, spec.temperature, tags)
        stop = _attempt(spec, ctx, retry_model, f"{prompt}\n\n{instruction}", clock)
    return _guarded(ctx, _finalize(spec, ctx, stop))


def _tag_warnings(extra: Sequence[str]) -> list[str]:
    return [
        f"caller litellm tag in reserved namespace '{namespace}:' was dropped"
        for namespace in dropped_caller_tags(extra)
    ]


def _first_attempt(
    spec: AgentSpec,
    ctx: InvocationContext,
    factory: ModelFactory,
    model_id: str,
    tags: list[str],
    prompt: str,
    clock: _WallClock,
) -> StopReason:
    try:
        model = factory(model_id, spec.max_tokens, spec.temperature, tags)
        return _attempt(spec, ctx, model, prompt, clock)
    except Exception as exc:
        fallback = spec.retry_model_id
        if fallback is None or not _is_overload(exc) or ctx.finish_result is not None:
            raise
    ctx.warnings.append(FALLBACK_WARNING)
    model = factory(fallback, spec.max_tokens, spec.temperature, tags)
    return _attempt(spec, ctx, model, prompt, clock)


def _guarded(ctx: InvocationContext, result: InvocationResult) -> InvocationResult:
    guards = ctx.services.get("result_guards")
    if not isinstance(guards, list):
        return result
    for guard in guards:
        result = guard(result, ctx.services)
    return result


def _services_with_skills(
    services: dict[str, Any] | None, request: InvocationRequest, agent: str
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(services or {})
    if request.skills and skillset_from_services(merged) is None:
        merged["skills"] = skillset_from_payload(request, agent)
    return merged


def _skill_sections() -> list[str]:
    skillset = skillset_from_services(current().services)
    if skillset is None:
        return []
    section = skills_prompt_section(skillset)
    return [section] if section else []


def _task_prompt(spec: AgentSpec, request: InvocationRequest) -> str:
    action = request.mode.value if request.mode is not None else None
    task = spec.render_task(request.target, action, request.project)
    return f"{task}\n\n{request.prompt}"


def _attempt(
    spec: AgentSpec,
    ctx: InvocationContext,
    model: Model,
    prompt: str,
    clock: _WallClock,
) -> StopReason:
    limits: Limits = {"turns": spec.max_iterations}
    remaining = _remaining_tokens(ctx)
    if remaining is not None:
        if remaining <= 0:
            return "limit_total_tokens"
        limits["total_tokens"] = remaining
    agent = create_agent(spec, model)
    clock.bind(agent)
    try:
        return agent(prompt, limits=limits).stop_reason
    except MaxTokensReachedException:
        return "max_tokens"
    finally:
        clock.unbind()
        usage = agent.event_loop_metrics.accumulated_usage
        ctx.input_tokens += usage["inputTokens"]
        ctx.output_tokens += usage["outputTokens"]


def _remaining_tokens(ctx: InvocationContext) -> int | None:
    if ctx.max_run_tokens is None:
        return None
    used = ctx.input_tokens + ctx.output_tokens
    return max(ctx.max_run_tokens - used, 0)


def _retry_instruction(stop: StopReason, ctx: InvocationContext) -> str | None:
    if ctx.finish_result is not None or stop in _NO_RETRY_STOPS:
        return None
    if ctx.budget_stop is not None or ctx.invalid_finish_attempts >= MAX_INVALID_FINISH:
        return None
    return _TRUNCATED if stop == "max_tokens" else _MISSING_FINISH


def _finalize(
    spec: AgentSpec, ctx: InvocationContext, stop: StopReason
) -> InvocationResult:
    payload = ctx.finish_result
    if payload is not None:
        findings = [finding.with_id() for finding in payload.findings]
        return _result(
            spec,
            ctx,
            RunStatus.COMPLETE,
            payload.verdict,
            payload.summary,
            findings,
            payload.data,
        )
    ctx.warnings.append(_incomplete_reason(stop, ctx))
    return _result(
        spec, ctx, RunStatus.INCOMPLETE, Verdict.INCOMPLETE, _INCOMPLETE_SUMMARY
    )


def _incomplete_reason(stop: StopReason, ctx: InvocationContext) -> str:
    if ctx.budget_stop is not None:
        return ctx.budget_stop
    if ctx.invalid_finish_attempts >= MAX_INVALID_FINISH:
        return "finish() was rejected twice; no result was produced"
    if stop == "limit_total_tokens":
        return TOKEN_CEILING_REASON
    if stop == "limit_turns":
        return "iteration limit reached before finish(); result is incomplete"
    return f"run ended with stop reason '{stop}' without finish(); result is incomplete"


def _result(
    spec: AgentSpec,
    ctx: InvocationContext,
    status: RunStatus,
    verdict: Verdict,
    summary: str,
    findings: Sequence[Finding] = (),
    data: dict[str, Any] | None = None,
) -> InvocationResult:
    warnings = list(ctx.warnings)
    warnings.extend(_string_items(ctx.services.get("config_warnings")))
    skillset = skillset_from_services(ctx.services)
    if skillset is not None:
        warnings.extend(skillset.warnings)
    if ctx.gate.blocked:
        warnings.append(
            f"dry-run blocked {len(ctx.gate.blocked)} external write attempt(s)"
        )
    return InvocationResult(
        agent=spec.name,
        status=status,
        verdict=verdict,
        summary=summary,
        findings=list(findings),
        stats=Stats(
            iterations=ctx.iterations,
            input_tokens=ctx.input_tokens,
            output_tokens=ctx.output_tokens,
            tool_calls=dict(ctx.tool_calls),
            skills_applied=applied_skills(ctx.services),
            config_hash=_config_hash(ctx.services),
        ),
        warnings=warnings,
        data=dict(data or {}),
    )


def _string_items(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _config_hash(services: dict[str, Any]) -> str | None:
    value = services.get("config_hash")
    return value if isinstance(value, str) else None


def _dry_run_note(gate: PostingGate) -> str:
    if gate.post_allowed:
        return (
            "External writes are enabled for this run. Use write tools only when the "
            "task requires them."
        )
    return (
        "DRY RUN: external writes are disabled for this run. "
        "Do not attempt to publish. "
        "Describe the intended writes in your finish() output instead."
    )
