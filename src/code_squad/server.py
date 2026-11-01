"""HTTP contract: /ping, /ready, /metrics, POST /invocations and GET /jobs/{id}.

``AGENT_NAME`` selects the agent (default ``michael``). ``Prefer: respond-async``
returns 202 with a ``job_id`` that ``GET /jobs/{id}`` polls. Jobs live in
``session.JobStore``; see that module for the single-replica caveat.

``/invocations`` and ``/jobs`` need ``SQUAD_API_TOKEN[_FILE]`` unless
``SQUAD_ALLOW_UNAUTHENTICATED=1``. An ``Idempotency-Key`` (header or body field) makes a
repeated request return the stored result, or 409 while the first run is in flight.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Final

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.concurrency import run_in_threadpool

from code_squad import __version__
from code_squad._common.auth import (
    API_TOKEN_ENV,
    bearer_matches,
    load_api_token,
    unauthenticated_allowed,
)
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
    InFlightRegistry,
    JobStore,
    MemorySessionStore,
    RedisSessionStore,
    SessionStore,
)
from code_squad._common.spec import AgentSpec
from code_squad._common.validation import (
    ValidationFailure,
    model_allowlist_errors,
    validate_invocation,
)
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
_MAX_REQUEST_ENV: Final = "SQUAD_MAX_REQUEST_BYTES"
_DEFAULT_MAX_REQUEST_BYTES: Final = 1_000_000
_MAX_KEY_LENGTH: Final = 128
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
    api_token = load_api_token(env)
    open_access = api_token is None and unauthenticated_allowed(env)
    if api_token is None:
        logger.warning(
            "%s is not set: /invocations and /jobs %s",
            API_TOKEN_ENV,
            "are open (SQUAD_ALLOW_UNAUTHENTICATED=1)"
            if open_access
            else "refuse every request; set the token or SQUAD_ALLOW_UNAUTHENTICATED=1",
        )
    base_services: ServicesFactory = services_factory or ServiceBuilder().build
    build_services = _with_extra_knowledge(base_services)
    store = session_store if session_store is not None else _default_store()
    jobs = JobStore(store)
    registry = InFlightRegistry(store)
    client = _specialist_client(wiring, env) if name == _DEFAULT_AGENT else None
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
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> Response:
        if not _authorized(request, api_token, open_access):
            return _unauthorized()
        if loaded.spec is None:
            return JSONResponse(
                status_code=503, content={"detail": "agent is not loaded"}
            )
        raw = await _json_body(request, _max_request_bytes(env, sources))
        try:
            req = validate_invocation(raw, loaded.spec)
            scoped = _claim_key(loaded.spec.name, req.idempotency_key, idempotency_key)
        except ValidationFailure as exc:
            return JSONResponse(status_code=422, content={"detail": exc.errors})
        if scoped is None:
            return await _dispatch(loaded.spec, req, prefer, background, None, registry)
        if not registry.try_acquire(scoped):
            return _replay(registry, scoped)
        try:
            response = await _dispatch(
                loaded.spec, req, prefer, background, scoped, registry
            )
        except BaseException:
            registry.release(scoped)
            raise
        _settle(registry, scoped, response)
        return response

    async def _dispatch(
        spec: AgentSpec,
        req: InvocationRequest,
        prefer: str | None,
        background: BackgroundTasks,
        scoped: str | None,
        registry: InFlightRegistry,
    ) -> Response:
        services = await run_in_threadpool(build_services, req, spec.name)
        errors = model_allowlist_errors(req, _allowed_models(services))
        if errors:
            return JSONResponse(status_code=422, content={"detail": errors})
        plan = plan_run(spec, services)
        if plan.disabled:
            refused = disabled_result(spec, services)
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
                registry=registry,
                scoped_key=scoped,
            )
            return JSONResponse(
                status_code=202, content={"job_id": job_id}, background=background
            )
        result = await _execute(
            plan.spec, req, services, factory, plan.post_override, invoker
        )
        return JSONResponse(content=result.model_dump(mode="json"))

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str, request: Request) -> JSONResponse:
        if not _authorized(request, api_token, open_access):
            return _unauthorized()
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
                inflight=registry,
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


def _authorized(request: Request, api_token: str | None, open_access: bool) -> bool:
    if api_token is None:
        return open_access
    return bearer_matches(request.headers.get("authorization"), api_token)


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "missing or invalid bearer token"},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _specialist_client(
    wiring: MichaelWiring | None, env: Mapping[str, str]
) -> SpecialistClient:
    if wiring is not None and wiring.specialist_client is not None:
        return wiring.specialist_client
    return HttpSpecialistClient(httpx.Client(), breakers=CircuitBreakers(), env=env)


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


def _max_request_bytes(env: Mapping[str, str], sources: ConfigSources) -> int:
    raw = env.get(_MAX_REQUEST_ENV, "").strip()
    if raw:
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        logger.warning("%s must be a positive integer; default used", _MAX_REQUEST_ENV)
        return _DEFAULT_MAX_REQUEST_BYTES
    try:
        config = SquadConfig.model_validate(load_org(sources))
    except (ConfigError, ValueError):
        return _DEFAULT_MAX_REQUEST_BYTES
    limit: Any = getattr(getattr(config, "limits", None), "max_request_bytes", None)
    if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
        return limit
    return _DEFAULT_MAX_REQUEST_BYTES


async def _json_body(request: Request, limit: int) -> Any:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="request body is too large")
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > limit:
            raise HTTPException(status_code=413, detail="request body is too large")
    try:
        return json.loads(bytes(received))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="request body must be valid JSON"
        ) from exc


def _claim_key(agent: str, body_key: str | None, header_key: str | None) -> str | None:
    errors: list[str] = []
    if header_key is not None and len(header_key) > _MAX_KEY_LENGTH:
        errors.append(f"Idempotency-Key must be at most {_MAX_KEY_LENGTH} characters")
    if body_key is not None and header_key is not None and body_key != header_key:
        errors.append(
            "idempotency key in the body and the Idempotency-Key header differ"
        )
    if errors:
        raise ValidationFailure(errors)
    key = body_key or header_key
    return f"{agent}:{key}" if key else None


def _replay(registry: InFlightRegistry, scoped: str) -> JSONResponse:
    entry = registry.state(scoped)
    if entry is not None and entry.get("state") == "done":
        stored: dict[str, Any] = entry.get("result") or {}
        return JSONResponse(
            status_code=int(stored.get("status_code", 200)),
            content=stored.get("body"),
        )
    return JSONResponse(status_code=409, content={"status": "in_flight"})


def _settle(registry: InFlightRegistry, scoped: str, response: Response) -> None:
    if response.status_code == 202:
        return  # the background job completes or releases the key
    if response.status_code == 200:
        body: Any = json.loads(bytes(response.body))
        registry.complete(scoped, {"status_code": 200, "body": body})
        return
    registry.release(scoped)


def _allowed_models(services: Mapping[str, Any]) -> list[str]:
    config: Any = getattr(services.get("config"), "config", None)
    allowed: Any = getattr(getattr(config, "llm", None), "allowed_models", None)
    return [str(item) for item in allowed] if isinstance(allowed, list) else []


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
    *,
    registry: InFlightRegistry | None = None,
    scoped_key: str | None = None,
) -> None:
    jobs.update(job_id, "running")
    started = time.perf_counter()
    try:
        result = invoker(spec, req, services, factory, post_override)
    except Exception as exc:
        logger.exception(
            "job failed",
            extra={
                "agent": spec.name,
                "invocation_id": job_id,
                "error_type": type(exc).__name__,
            },
        )
        jobs.update(job_id, "failed")
        if registry is not None and scoped_key is not None:
            registry.release(scoped_key)
        return
    _finish(result, job_id, time.perf_counter() - started)
    body = result.model_dump(mode="json")
    jobs.update(job_id, "done", body)
    if registry is not None and scoped_key is not None:
        registry.complete(scoped_key, {"status_code": 200, "body": body})


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
