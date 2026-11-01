"""Orchestrator: intent, routing, fan-out, aggregation and the single publication.

- ``mr_review``: route the change deterministically, score its risk, call the selected
  specialists in parallel with ``post: false`` (unless ``routing.specialists_post``),
  merge their findings and publish one consolidated outcome through ``publish``.
- ``incident``: darryl in troubleshoot mode, read-only. Its summary is posted as an
  issue
  comment only when posting is allowed and the target is a number.
- ``implement``: pam in implementer mode. pam opens its own change request, so the post
  flag is passed through and michael writes nothing itself.
- ``question``: michael's own spec (read_knowledge and finish only).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from code_squad._common.config.loader import EffectiveConfig
from code_squad._common.config.schema import SquadConfig
from code_squad._common.contract import (
    Finding,
    InvocationRequest,
    InvocationResult,
    Posted,
    RunStatus,
    Stats,
    Verdict,
)
from code_squad._common.findings import PublishOptions
from code_squad._common.model import ModelFactory, get_model_factory
from code_squad._common.posting import DryRunError, PostingGate
from code_squad._common.runtime import run_task
from code_squad._common.spec import AgentSpec
from code_squad._common.vcs.base import (
    ChangeRequestRef,
    NotFoundError,
    VcsError,
    VcsProvider,
)
from code_squad.michael import SPEC as MICHAEL_SPEC
from code_squad.michael.aggregate import aggregate, render_summary
from code_squad.michael.fanout import (
    SpecialistClient,
    SpecialistOutcome,
    fan_out,
    idempotency_key,
    trace_headers,
)
from code_squad.michael.intent import (
    Classifier,
    Intent,
    classify_intent,
    is_numeric_target,
)
from code_squad.michael.llm import (
    llm_intent_classifier,
    llm_intent_enabled,
    llm_summarizer,
    llm_summary_enabled,
)
from code_squad.michael.publish import publish_consolidated
from code_squad.michael.risk import RiskAssessment, risk_tier
from code_squad.michael.routing import RoutePlan, add_agents, route

Invoker = Callable[
    [AgentSpec, InvocationRequest, dict[str, Any], ModelFactory, bool | None],
    InvocationResult,
]
RouteClassifier = Callable[[tuple[str, ...]], Sequence[str]]
Summarizer = Callable[[str], str]

SPECIALISTS: Final[tuple[str, ...]] = ("jim", "angela", "dwight", "darryl")
_MANIFESTS: Final[tuple[str, ...]] = (
    "package.json",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
)
_YAML_SUFFIXES: Final = (".yaml", ".yml")
_MAX_YAML_READS: Final = 30
_MAX_FILE_CHARS: Final = 200_000
_HIGH_TIER_HINT: Final = "Scope: full review. The change is in the high risk tier."


@dataclass(frozen=True)
class _Run:
    request: InvocationRequest
    services: dict[str, Any]
    gate: PostingGate
    intent: Intent
    factory: ModelFactory
    post_override: bool | None


@dataclass(frozen=True)
class Orchestrator:
    client: SpecialistClient
    model_factory: ModelFactory | None = None
    intent_classifier: Classifier | None = None
    route_classifier: RouteClassifier | None = None
    summarizer: Summarizer | None = None

    def run(
        self,
        request: InvocationRequest,
        services: dict[str, Any],
        *,
        post_override: bool | None = None,
        only_agents: Sequence[str] | None = None,
    ) -> InvocationResult:
        factory = self.model_factory or get_model_factory()
        found = services.get("intent_classifier")
        classifier: Classifier | None = (
            cast(Classifier, found) if callable(found) else self.intent_classifier
        )
        run = _Run(
            request=request,
            services=services,
            gate=_gate(request, post_override),
            intent=classify_intent(request, classifier),
            factory=factory,
            post_override=post_override,
        )
        if run.intent == "mr_review":
            return self._review(run, only_agents)
        if run.intent == "incident":
            return self._passthrough(run, "darryl", "troubleshoot", post=False)
        if run.intent == "implement":
            return self._passthrough(
                run, "pam", "implementer", post=run.gate.post_allowed
            )
        return _question(run)

    # ----- mr_review ---------------------------------------------------------

    def _review(self, run: _Run, only: Sequence[str] | None) -> InvocationResult:
        ref = change_request_ref(run.request)
        provider = _provider(run.services)
        if provider is None or ref is None:
            return _unavailable(run, "a project and a numeric target are required")
        try:
            change = provider.get_change_request(ref)
            diff = provider.get_diff(ref, change.head_sha)
        except VcsError as exc:
            return _unavailable(
                run, f"change request unavailable: {type(exc).__name__}"
            )
        head = change.head_sha
        config = _config(run.services)
        changed = [item.path for item in diff]
        disabled = frozenset(
            name for name, item in config.agents.items() if not item.enabled
        )
        plan = route(
            changed,
            _manifests(provider, ref.project, head, changed),
            config.routing,
            config.extra_agents,
            disabled=disabled,
        )
        notes: list[str] = []
        if plan.ambiguous and self.route_classifier is not None:
            plan = self._classified_plan(plan, changed, config, disabled, notes)
        risk = risk_tier(diff, config.routing)
        agents = [name for name in plan.agents if only is None or name in only]
        if not agents:
            return _unavailable(run, "no reviewer was selected for this change")
        outcomes = self._fan_out_review(agents, run.request, ref, head, risk, config)
        options = _publish_options(run.services)
        report = aggregate(
            outcomes,
            head_sha=head,
            risk=risk,
            major_threshold=options.major_threshold,
            warnings=notes,
        )
        facts = render_summary(
            report, intent="mr_review", changed_files=len(changed), stacks=plan.stacks
        )
        narrative = self._narrate(run.services, facts, notes)
        summary = (
            render_summary(
                report,
                intent="mr_review",
                changed_files=len(changed),
                stacks=plan.stacks,
                narrative=narrative,
            )
            if narrative
            else facts
        )
        publication = publish_consolidated(
            provider,
            ref,
            report,
            summary,
            gate=run.gate,
            options=options,
        )
        data: dict[str, Any] = {
            "intent": "mr_review",
            "risk": {"tier": risk.tier, "reasons": list(risk.reasons)},
            "agents": dict(report.statuses),
            "contributors": {
                key: list(value) for key, value in report.contributors.items()
            },
            "stacks": list(plan.stacks),
        }
        return _result(
            run,
            status=_status(report.verdict),
            verdict=report.verdict,
            summary=summary,
            findings=list(report.findings),
            outcomes=outcomes,
            posted=publication.posted,
            warnings=[*notes, *report.warnings, *publication.warnings],
            data=data,
        )

    def _classified_plan(
        self,
        plan: RoutePlan,
        changed: Sequence[str],
        config: SquadConfig,
        disabled: frozenset[str],
        notes: list[str],
    ) -> RoutePlan:
        classifier = self.route_classifier
        if classifier is None:
            return plan
        try:
            chosen = list(classifier(tuple(changed)))
        except Exception:
            notes.append(
                "route classifier failed; only always-run agents were selected"
            )
            return plan
        known = {*SPECIALISTS, *(item.id for item in config.extra_agents)}
        return add_agents(
            plan,
            chosen,
            reason="selected by the route classifier",
            known=known,
            disabled=disabled,
        )

    def _fan_out_review(
        self,
        agents: Sequence[str],
        request: InvocationRequest,
        ref: ChangeRequestRef,
        head: str,
        risk: RiskAssessment,
        config: SquadConfig,
    ) -> dict[str, SpecialistOutcome]:
        routing = config.routing
        base = request.idempotency_key or head

        def payload_for(agent: str) -> dict[str, Any]:
            hint = (
                _HIGH_TIER_HINT if risk.tier == "high" and agent == "dwight" else None
            )
            return _review_payload(request, ref, head, routing.specialists_post, hint)

        return fan_out(
            agents,
            self.client.bind(routing.specialist_urls),
            payload_for=payload_for,
            key_for=lambda agent: idempotency_key(base, agent),
            timeouts=routing.timeouts_seconds,
            concurrency=routing.fan_out_concurrency,
            trace=trace_headers(),
        )

    def _narrate(
        self, services: dict[str, Any], facts: str, notes: list[str]
    ) -> str | None:
        found = services.get("summarizer")
        summarizer = cast(Summarizer, found) if callable(found) else self.summarizer
        if summarizer is None:
            return None
        try:
            text = summarizer(facts).strip()
        except Exception:
            notes.append("summary model failed; the deterministic summary was used")
            return None
        return text or None

    # ----- incident and implement (pass-through) -----------------------------

    def _passthrough(
        self, run: _Run, agent: str, mode: str, *, post: bool
    ) -> InvocationResult:
        request = run.request
        routing = _config(run.services).routing
        base = request.idempotency_key or request.target or "request"
        outcomes = fan_out(
            (agent,),
            self.client.bind(routing.specialist_urls),
            payload_for=lambda _agent: _passthrough_payload(request, mode, post),
            key_for=lambda name: idempotency_key(base, name),
            timeouts=routing.timeouts_seconds,
            concurrency=1,
            trace=trace_headers(),
        )
        outcome = outcomes[agent]
        result = outcome.result
        summary = (
            result.summary
            if result is not None
            else f"{agent} did not complete: {outcome.error or outcome.status}."
        )
        posted = Posted()
        notes: list[str] = []
        if run.intent == "incident" and result is not None:
            posted, notes = _comment_on_issue(run, summary)
        specialist_warnings = [
            f"{agent}: {item}" for item in (result.warnings if result else [])
        ]
        data: dict[str, Any] = {
            "intent": run.intent,
            "agents": {agent: outcome.status},
            "specialist": dict(result.data) if result is not None else {},
        }
        return _result(
            run,
            status=result.status if result is not None else RunStatus.INCOMPLETE,
            verdict=result.verdict if result is not None else Verdict.INCOMPLETE,
            summary=summary,
            findings=list(result.findings) if result is not None else [],
            outcomes=outcomes,
            posted=posted,
            warnings=[*notes, *specialist_warnings],
            data=data,
        )


def make_invoker(client: SpecialistClient) -> Invoker:
    """Invocation hook for the HTTP server: michael requests use the orchestrator."""

    def invoke(
        spec: AgentSpec,
        request: InvocationRequest,
        services: dict[str, Any],
        factory: ModelFactory,
        post_override: bool | None,
    ) -> InvocationResult:
        summarizer = (
            llm_summarizer(factory) if llm_summary_enabled(os.environ) else None
        )
        classifier = (
            llm_intent_classifier(factory) if llm_intent_enabled(os.environ) else None
        )
        orchestrator = Orchestrator(
            client=client,
            model_factory=factory,
            intent_classifier=classifier,
            summarizer=summarizer,
        )
        return orchestrator.run(request, services, post_override=post_override)

    return invoke


def orchestrate(
    request: InvocationRequest,
    services: dict[str, Any],
    *,
    client: SpecialistClient,
    model_factory: ModelFactory | None = None,
    post_override: bool | None = None,
) -> InvocationResult:
    return Orchestrator(client=client, model_factory=model_factory).run(
        request, services, post_override=post_override
    )


def change_request_ref(request: InvocationRequest) -> ChangeRequestRef | None:
    if request.project is None or not is_numeric_target(request.target):
        return None
    number = (request.target or "").strip().lstrip("!#")
    return ChangeRequestRef(request.project, int(number))


def _question(run: _Run) -> InvocationResult:
    result = run_task(
        MICHAEL_SPEC,
        run.request,
        services=run.services,
        model_factory=run.factory,
        post_override=run.post_override,
    )
    return result.model_copy(update={"data": {**result.data, "intent": "question"}})


def _comment_on_issue(run: _Run, body: str) -> tuple[Posted, list[str]]:
    request = run.request
    provider = _provider(run.services)
    if (
        provider is None
        or request.project is None
        or not is_numeric_target(request.target)
    ):
        return Posted(), []
    try:
        run.gate.require_write("comment_on_issue")
    except DryRunError:
        return Posted(), []
    number = int((request.target or "").strip().lstrip("!#"))
    try:
        provider.comment_on_issue(request.project, number, body)
    except VcsError as exc:
        return Posted(), [f"issue comment failed: {type(exc).__name__}"]
    return Posted(notes=1), []


def _unavailable(run: _Run, reason: str) -> InvocationResult:
    message = f"No review was run: {reason}."
    return InvocationResult(
        agent=MICHAEL_SPEC.name,
        status=RunStatus.INCOMPLETE,
        verdict=Verdict.INCOMPLETE,
        summary=message,
        stats=Stats(config_hash=_config_hash(run.services)),
        warnings=_warnings(run, [reason]),
        data={"intent": run.intent},
    )


def _result(
    run: _Run,
    *,
    status: RunStatus,
    verdict: Verdict,
    summary: str,
    findings: list[Finding],
    outcomes: dict[str, SpecialistOutcome],
    posted: Posted,
    warnings: list[str],
    data: dict[str, Any],
) -> InvocationResult:
    results = [item.result for item in outcomes.values() if item.result is not None]
    stats = Stats(
        iterations=sum(item.stats.iterations for item in results),
        input_tokens=sum(item.stats.input_tokens for item in results),
        output_tokens=sum(item.stats.output_tokens for item in results),
        config_hash=_config_hash(run.services),
    )
    return InvocationResult(
        agent=MICHAEL_SPEC.name,
        status=status,
        verdict=verdict,
        summary=summary,
        findings=findings,
        stats=stats,
        posted=posted,
        warnings=_warnings(run, warnings),
        data=data,
    )


def _status(verdict: Verdict) -> RunStatus:
    return RunStatus.INCOMPLETE if verdict is Verdict.INCOMPLETE else RunStatus.COMPLETE


def _gate(request: InvocationRequest, post_override: bool | None) -> PostingGate:
    if post_override is False:
        return PostingGate(post_allowed=False)
    return PostingGate.from_request(request)


def _warnings(run: _Run, extra: Sequence[str]) -> list[str]:
    base = run.services.get("config_warnings")
    items = [str(item) for item in base] if isinstance(base, list) else []
    items.extend(extra)
    if run.gate.blocked:
        items.append(
            f"dry-run blocked {len(run.gate.blocked)} external write attempt(s)"
        )
    return items


def _config_hash(services: dict[str, Any]) -> str | None:
    value = services.get("config_hash")
    return value if isinstance(value, str) else None


def _provider(services: dict[str, Any]) -> VcsProvider | None:
    value = services.get("vcs")
    return cast(VcsProvider, value) if value is not None else None


def _config(services: dict[str, Any]) -> SquadConfig:
    effective = services.get("config")
    if isinstance(effective, EffectiveConfig):
        return effective.config
    return SquadConfig()


def _publish_options(services: dict[str, Any]) -> PublishOptions:
    value = services.get("publish_options")
    return value if isinstance(value, PublishOptions) else PublishOptions()


def _manifests(
    provider: VcsProvider, project: str, head: str, changed: Sequence[str]
) -> dict[str, str]:
    found: dict[str, str] = {}
    for name in _MANIFESTS:
        text = _read(provider, project, name, head)
        if text is not None:
            found[name] = text
    yaml_paths = [path for path in changed if path.endswith(_YAML_SUFFIXES)]
    for path in yaml_paths[:_MAX_YAML_READS]:
        text = _read(provider, project, path, head)
        if text is not None:
            found[path] = text
    return found


def _read(provider: VcsProvider, project: str, path: str, ref: str) -> str | None:
    try:
        return provider.read_file(project, path, ref)[:_MAX_FILE_CHARS]
    except (NotFoundError, VcsError):
        return None


def _review_payload(
    request: InvocationRequest,
    ref: ChangeRequestRef,
    head: str,
    post: bool,
    hint: str | None,
) -> dict[str, Any]:
    prompt = (
        f"Review change request {ref.number} in project {ref.project} "
        f"at head {head[:12]}."
    )
    if hint:
        prompt = f"{prompt} {hint}"
    payload: dict[str, Any] = {
        "prompt": prompt,
        "project": ref.project,
        "target": str(ref.number),
        "mode": "review",
        "post": post,
    }
    return _with_common(payload, request)


def _passthrough_payload(
    request: InvocationRequest, mode: str, post: bool
) -> dict[str, Any]:
    payload: dict[str, Any] = {"prompt": request.prompt, "mode": mode, "post": post}
    if request.project is not None:
        payload["project"] = request.project
    if request.target is not None:
        payload["target"] = request.target
    return _with_common(payload, request)


def _with_common(payload: dict[str, Any], request: InvocationRequest) -> dict[str, Any]:
    if request.litellm_tags:
        payload["litellm_tags"] = list(request.litellm_tags)
    if request.skills:
        payload["skills"] = [item.model_dump(mode="json") for item in request.skills]
    return payload
