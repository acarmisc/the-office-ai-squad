"""HTTP contract: /ping, /ready, /metrics, POST /invocations and GET /jobs/{id}.

``AGENT_NAME`` selects the agent (default ``michael``). ``Prefer: respond-async``
returns 202 with a ``job_id`` that ``GET /jobs/{id}`` polls. Jobs live in
``session.JobStore``; see that module for the single-replica caveat.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Final

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.concurrency import run_in_threadpool

from code_squad import __version__
from code_squad._common.config.errors import ConfigError
from code_squad._common.config.loader import ConfigSources, load_org
from code_squad._common.config.schema import SquadConfig
from code_squad._common.contract import InvocationRequest, InvocationResult
from code_squad._common.model import ModelFactory, get_model_factory
from code_squad._common.observability import (
    REGISTRY,
    configure_logging,
    configure_tracing,
    record_result,
    span,
)
from code_squad._common.registry import (
    AGENT_IDS,
    extra_knowledge_dirs,
    get_spec,
    register_extra_agents,
)
from code_squad._common.services import (
    ServiceBuilder,
    disabled_result,
    plan_run,
    runner_for,
    sources_from_env,
)
from code_squad._common.session import (
    JobStore,
    MemorySessionStore,
    RedisSessionStore,
    SessionStore,
)
from code_squad._common.spec import AgentSpec
from code_squad._common.validation import ValidationFailure, validate_invocation
from code_squad.michael.fanout import (
    CircuitBreakers,
    HttpSpecialistClient,
    SpecialistClient,
)
from code_squad.michael.gateway import (
    MichaelWiring,
    WebhookGateway,
    enabled_providers,
    register_webhook_routes,
)
from code_squad.michael.orchestrator import Invoker, make_invoker

logger = logging.getLogger(__name__)

_DEFAULT_AGENT: Final = "michael"
ServicesFactory = Callable[[InvocationRequest, str], dict[str, Any]]


@dataclass(frozen=True)
class _Loaded:
    spec: AgentSpec | None
    error: str | None


def create_app(
    agent_name: str | None = None,
    *,
    model_factory: ModelFactory | None = None,
    services_factory: ServicesFactory | None = None,
    session_store: SessionStore | None = None,
    wiring: MichaelWiring | None = None,
) -> FastAPI:
    name = agent_name or os.environ.get("AGENT_NAME", _DEFAULT_AGENT)
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    configure_tracing(f"code-squad-{name}")
    env = (
        dict(wiring.env)
        if wiring is not None and wiring.env is not None
        else dict(os.environ)
    )
    sources = wiring.config_sources if wiring is not None else None
    sources = sources if sources is not None else sources_from_env(env)
    loaded = _load(name, sources)
    base_services: ServicesFactory = services_factory or ServiceBuilder().build
    build_services = _with_extra_knowledge(base_services)
    jobs = JobStore(session_store or _default_store())
    client = _specialist_client(wiring) if name == _DEFAULT_AGENT else None
    invoker: Invoker = make_invoker(client) if client is not None else _run_agent
    app = FastAPI(title="Code Squad", version=__version__)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> JSONResponse:
        if loaded.spec is None:
            body = {"status": "not_ready", "agent": name, "error": loaded.error}
            return JSONResponse(status_code=503, content=body)
        return JSONResponse({"status": "ready", "agent": name})

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(
            content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST
        )

    @app.post("/invocations")
    async def invoke(
        request: Request,
        background: BackgroundTasks,
        prefer: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        if loaded.spec is None:
            return JSONResponse(
                status_code=503, content={"detail": "agent is not loaded"}
            )
        raw = await _json_body(request)
        try:
            req = validate_invocation(raw, loaded.spec)
        except ValidationFailure as exc:
            return JSONResponse(status_code=422, content={"detail": exc.errors})
        services = await run_in_threadpool(build_services, req, loaded.spec.name)
        plan = plan_run(loaded.spec, services)
        if plan.disabled:
            refused = disabled_result(loaded.spec, services)
            _finish(refused, uuid.uuid4().hex, 0.0)
            return JSONResponse(content=refused.model_dump(mode="json"))
        factory = model_factory or get_model_factory()
        if _wants_async(prefer):
            job_id = uuid.uuid4().hex
            jobs.create(job_id)
            background.add_task(
                _run_job,
                jobs,
                job_id,
                plan.spec,
                req,
                services,
                factory,
                plan.post_override,
                invoker,
            )
            return JSONResponse(
                status_code=202, content={"job_id": job_id}, background=background
            )
        result = await _execute(
            plan.spec, req, services, factory, plan.post_override, invoker
        )
        return JSONResponse(content=result.model_dump(mode="json"))

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> JSONResponse:
        entry = jobs.get(job_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return JSONResponse({"job_id": job_id, **entry})

    if client is not None:
        providers = enabled_providers(env)
        if providers:
            gateway = WebhookGateway(
                env=env,
                sources=sources,
                jobs=jobs,
                client=client,
                services_factory=build_services,
                model_factory=model_factory,
                secrets=wiring.secret_provider if wiring is not None else None,
            )
            register_webhook_routes(app, gateway, providers)

    return app


def _load(name: str, sources: ConfigSources) -> _Loaded:
    try:
        if name not in AGENT_IDS:
            _register_extras(sources)
        return _Loaded(spec=get_spec(name), error=None)
    except Exception as exc:
        logger.error("agent failed to load", extra={"agent": name})
        return _Loaded(spec=None, error=type(exc).__name__)


def _register_extras(sources: ConfigSources) -> None:
    try:
        org = load_org(sources)
    except ConfigError:
        return
    register_extra_agents(SquadConfig.model_validate(org).extra_agents)


def _with_extra_knowledge(base: ServicesFactory) -> ServicesFactory:
    def build(request: InvocationRequest, agent: str) -> dict[str, Any]:
        services = base(request, agent)
        extra = extra_knowledge_dirs(agent)
        if extra:
            current = services.get("knowledge_extra_dirs")
            existing = list(current) if isinstance(current, list) else []
            services["knowledge_extra_dirs"] = [*existing, *extra]
        return services

    return build


def _specialist_client(wiring: MichaelWiring | None) -> SpecialistClient:
    if wiring is not None and wiring.specialist_client is not None:
        return wiring.specialist_client
    return HttpSpecialistClient(
        httpx.Client(), breakers=CircuitBreakers(), env=dict(os.environ)
    )


def _run_agent(
    spec: AgentSpec,
    req: InvocationRequest,
    services: dict[str, Any],
    factory: ModelFactory,
    post_override: bool | None,
) -> InvocationResult:
    runner = runner_for(spec.name)
    return runner(
        spec,
        req,
        services=services,
        model_factory=factory,
        post_override=post_override,
    )


def _default_store() -> SessionStore:
    url = os.environ.get("SESSION_STORE_URL", "")
    if url.startswith(("redis://", "rediss://")):
        return RedisSessionStore(url)
    return MemorySessionStore()


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="request body must be valid JSON"
        ) from exc


def _wants_async(prefer: str | None) -> bool:
    return prefer is not None and "respond-async" in prefer.lower()


async def _execute(
    spec: AgentSpec,
    req: InvocationRequest,
    services: dict[str, Any],
    factory: ModelFactory,
    post_override: bool | None,
    invoker: Invoker,
) -> InvocationResult:
    invocation_id = uuid.uuid4().hex
    started = time.perf_counter()
    with span("invocation", agent=spec.name, invocation_id=invocation_id):
        result = await run_in_threadpool(
            invoker, spec, req, services, factory, post_override
        )
    _finish(result, invocation_id, time.perf_counter() - started)
    return result


def _run_job(
    jobs: JobStore,
    job_id: str,
    spec: AgentSpec,
    req: InvocationRequest,
    services: dict[str, Any],
    factory: ModelFactory,
    post_override: bool | None,
    invoker: Invoker,
) -> None:
    jobs.update(job_id, "running")
    started = time.perf_counter()
    try:
        result = invoker(spec, req, services, factory, post_override)
    except Exception:
        logger.error("job failed", extra={"agent": spec.name, "invocation_id": job_id})
        jobs.update(job_id, "failed")
        return
    _finish(result, job_id, time.perf_counter() - started)
    jobs.update(job_id, "done", result.model_dump(mode="json"))


def _finish(result: InvocationResult, invocation_id: str, duration: float) -> None:
    record_result(result, duration)
    logger.info(
        "invocation finished",
        extra={
            "agent": result.agent,
            "status": result.status.value,
            "duration_ms": round(duration * 1000),
            "iterations": result.stats.iterations,
            "invocation_id": invocation_id,
        },
    )


app = create_app()
