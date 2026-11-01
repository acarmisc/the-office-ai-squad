from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from strands import Agent
from strands.models.model import Model
from strands.types.event_loop import StopReason
from strands.types.exceptions import MaxTokensReachedException

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
from code_squad._common.model import ModelFactory, get_model_factory, litellm_tags
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
    ctx = InvocationContext(
        agent=spec.name,
        request=request,
        gate=_gate(request, post_override),
        services=_services_with_skills(services, request, spec.name),
    )
    factory = model_factory or get_model_factory()
    with use_context(ctx):
        try:
            return _run(spec, request, ctx, factory)
        except Exception as exc:
            ctx.warnings.append(f"model call failed: {type(exc).__name__}")
            return _result(
                spec, ctx, RunStatus.FAILED, Verdict.INCOMPLETE, _FAILED_SUMMARY
            )


def _gate(request: InvocationRequest, post_override: bool | None) -> PostingGate:
    if post_override is False:
        return PostingGate(post_allowed=False)
    return PostingGate.from_request(request)


def _run(
    spec: AgentSpec,
    request: InvocationRequest,
    ctx: InvocationContext,
    factory: ModelFactory,
) -> InvocationResult:
    model_id = request.model or spec.model_id
    tags = litellm_tags(spec.name, request.project, request.litellm_tags)
    prompt = _task_prompt(spec, request)
    stop = _attempt(
        spec, ctx, factory(model_id, spec.max_tokens, spec.temperature, tags), prompt
    )
    instruction = _retry_instruction(stop, ctx)
    if instruction is not None:
        retry_id = (
            spec.retry_model_id
            if stop == "max_tokens" and spec.retry_model_id
            else model_id
        )
        retry_model = factory(retry_id, spec.max_tokens, spec.temperature, tags)
        stop = _attempt(spec, ctx, retry_model, f"{prompt}\n\n{instruction}")
    return _finalize(spec, ctx, stop)


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
    spec: AgentSpec, ctx: InvocationContext, model: Model, prompt: str
) -> StopReason:
    agent = create_agent(spec, model)
    try:
        return agent(prompt, limits={"turns": spec.max_iterations}).stop_reason
    except MaxTokensReachedException:
        return "max_tokens"
    finally:
        usage = agent.event_loop_metrics.accumulated_usage
        ctx.input_tokens += usage["inputTokens"]
        ctx.output_tokens += usage["outputTokens"]


def _retry_instruction(stop: StopReason, ctx: InvocationContext) -> str | None:
    if ctx.finish_result is not None or stop == "limit_turns":
        return None
    if ctx.invalid_finish_attempts >= MAX_INVALID_FINISH:
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
    if ctx.invalid_finish_attempts >= MAX_INVALID_FINISH:
        return "finish() was rejected twice; no result was produced"
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
