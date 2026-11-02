"""The shared invocation path: validate, build services, plan, run.

The HTTP server, the ``squad`` CLI and the GitHub Actions review all run an invocation
the same way. The server splits the steps so that it can answer 422 before it claims an
idempotency key and run michael in the background; ``execute_invocation`` runs them in
one call for in-process callers.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from code_squad._common.contract import InvocationRequest, InvocationResult
from code_squad._common.model import ModelFactory, get_model_factory
from code_squad._common.registry import extra_knowledge_dirs, get_spec
from code_squad._common.services import (
    CHANGE_REQUEST_UNAVAILABLE_KEY,
    ServiceBuilder,
    disabled_result,
    plan_run,
    runner_for,
    unavailable_result,
)
from code_squad._common.spec import AgentSpec
from code_squad._common.validation import model_allowlist_errors, validate_invocation

ServicesFactory = Callable[[InvocationRequest, str], dict[str, Any]]
Invoker = Callable[
    [AgentSpec, InvocationRequest, dict[str, Any], ModelFactory, bool | None],
    InvocationResult,
]


class InvocationRefused(Exception):
    """The request names a model outside the organisation's allow-list."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class PreparedInvocation:
    spec: AgentSpec
    request: InvocationRequest
    services: dict[str, Any]
    post_override: bool | None
    disabled: InvocationResult | None = None


def default_services_factory() -> ServicesFactory:
    return with_extra_knowledge(ServiceBuilder().build)


def with_extra_knowledge(base: ServicesFactory) -> ServicesFactory:
    def build(request: InvocationRequest, agent: str) -> dict[str, Any]:
        services = base(request, agent)
        extra = extra_knowledge_dirs(agent)
        if extra:
            current = services.get("knowledge_extra_dirs")
            existing = list(current) if isinstance(current, list) else []
            services["knowledge_extra_dirs"] = [*existing, *extra]
        return services

    return build


def prepare_invocation(
    spec: AgentSpec, request: InvocationRequest, services_factory: ServicesFactory
) -> PreparedInvocation:
    """Build the services, check the model allow-list and apply the agent settings.

    Raises ``InvocationRefused`` for a model outside the allow-list. An agent that the
    configuration disables comes back with ``disabled`` set and is not run.
    """
    services = services_factory(request, spec.name)
    errors = model_allowlist_errors(request, _allowed_models(services))
    if errors:
        raise InvocationRefused(errors)
    plan = plan_run(spec, services)
    refused = disabled_result(spec, services) if plan.disabled else None
    if refused is None and services.get(CHANGE_REQUEST_UNAVAILABLE_KEY):
        refused = unavailable_result(spec, services)
    return PreparedInvocation(plan.spec, request, services, plan.post_override, refused)


def run_prepared(
    prepared: PreparedInvocation,
    *,
    model_factory: ModelFactory | None = None,
    invoker: Invoker | None = None,
) -> InvocationResult:
    if prepared.disabled is not None:
        return prepared.disabled
    factory = model_factory or get_model_factory()
    run = invoker or run_with_runner
    return run(
        prepared.spec,
        prepared.request,
        prepared.services,
        factory,
        prepared.post_override,
    )


def run_with_runner(
    spec: AgentSpec,
    request: InvocationRequest,
    services: dict[str, Any],
    factory: ModelFactory,
    post_override: bool | None,
) -> InvocationResult:
    runner = runner_for(spec.name)
    return runner(
        spec,
        request,
        services=services,
        model_factory=factory,
        post_override=post_override,
    )


def execute_invocation(
    agent_name: str,
    raw: Mapping[str, Any],
    *,
    services_factory: ServicesFactory | None = None,
    model_factory: ModelFactory | None = None,
    invoker: Invoker | None = None,
) -> InvocationResult:
    """Validate ``raw`` for the agent and run it.

    Raises ``UnknownAgentError`` for an unknown agent, ``ValidationFailure`` for a bad
    request and ``InvocationRefused`` for a model outside the allow-list.
    """
    spec = get_spec(agent_name)
    request = validate_invocation(dict(raw), spec)
    factory = services_factory or default_services_factory()
    prepared = prepare_invocation(spec, request, factory)
    return run_prepared(prepared, model_factory=model_factory, invoker=invoker)


def _allowed_models(services: Mapping[str, Any]) -> list[str]:
    config: Any = getattr(services.get("config"), "config", None)
    allowed: Any = getattr(getattr(config, "llm", None), "allowed_models", None)
    return [str(item) for item in allowed] if isinstance(allowed, list) else []
