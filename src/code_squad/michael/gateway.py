"""Webhook gateway for michael: GitLab and GitHub receivers with async orchestration.

Order of checks for each delivery: body size (413, before any signature work),
signature (401), JSON body (400), parseable event (400), supported event (202 ignored),
delivery id already recorded (200 duplicate), effective configuration (503 when
invalid), bot identity configured, trigger rules, single-flight per change request and
head, debounce. Only then a job is created and the response is 202 accepted; the
orchestration runs after the response. A delivery id is recorded only for final outcomes
(accepted or deliberately ignored). A refused delivery (401, 400, 413, 503, missing bot
identity) stays redeliverable.

Bot identity comes from ``vcs.bot_username`` in the organisation or registry layer. A
project without it ignores every event, which fails closed against bot loops.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Final, Literal

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from code_squad._common.config.errors import ConfigError
from code_squad._common.config.loader import (
    ConfigSources,
    EffectiveConfig,
    load_org,
    load_registry,
    resolve,
)
from code_squad._common.config.schema import SquadConfig
from code_squad._common.contract import InvocationRequest, InvocationResult, Mode
from code_squad._common.model import ModelFactory
from code_squad._common.observability import record_result
from code_squad._common.posting import DryRunError, PostingGate
from code_squad._common.registry import get_spec
from code_squad._common.secrets.base import (
    SecretNameError,
    SecretNotFoundError,
    SecretProvider,
)
from code_squad._common.secrets.factory import build_secret_provider
from code_squad._common.services import disabled_result, plan_run
from code_squad._common.session import InFlightRegistry, JobStore, MemorySessionStore
from code_squad._common.vcs.base import ChangeRequestRef
from code_squad._common.webhooks import (
    DeliveryDeduper,
    Intent,
    WebhookEvent,
    decide_trigger,
    parse_github_event,
    parse_gitlab_event,
    verify_github,
    verify_gitlab,
)
from code_squad.michael.fanout import SpecialistClient
from code_squad.michael.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

Provider = Literal["gitlab", "github"]
PROVIDERS: Final[tuple[Provider, ...]] = ("gitlab", "github")
WEBHOOK_PROVIDERS_ENV: Final = "WEBHOOK_PROVIDERS"
WEBHOOK_SECRETS_DIR_ENV: Final = "WEBHOOK_SECRETS_DIR"
MAX_WEBHOOK_BYTES_ENV: Final = "SQUAD_MAX_WEBHOOK_BYTES"
DEFAULT_MAX_WEBHOOK_BYTES: Final = 1_048_576
DOCS_URL_ENV: Final = "SQUAD_DOCS_URL"
HELP_TEXT: Final = (
    "Code Squad commands\n\n"
    "- `/squad review`: review this change request. Mentioning the bot also starts a "
    "review.\n"
    "- `/squad sec`: run the security review.\n"
    "- `/squad implement`: on an issue, start an implementation run. An issue assigned "
    "to the bot by an allowed user starts one too.\n"
    "- `/squad help`: show this list.\n\n"
    "Only users in the operator's allowed commenter list can start a run. Reviews are "
    "comments and a status; nothing is merged automatically."
)
_IDEMPOTENCY_LIMIT: Final = 128
_DEBOUNCE_HORIZON: Final = 3600.0
_DEBOUNCE_PRUNE_AT: Final = 1024
_REVIEW_INTENTS: Final = frozenset({"mr_review", "sec_review"})
_MODES: Final[dict[str, Mode]] = {
    "mr_review": Mode.REVIEW,
    "sec_review": Mode.REVIEW,
    "implement": Mode.IMPLEMENTER,
}


@dataclass(frozen=True)
class MichaelWiring:
    """Optional dependencies for michael, injected by tests and by the server."""

    env: Mapping[str, str] | None = None
    config_sources: ConfigSources | None = None
    secret_provider: SecretProvider | None = None
    specialist_client: SpecialistClient | None = None


@dataclass(frozen=True)
class WebhookResponse:
    status: int
    body: dict[str, Any]
    job: Callable[[], None] | None = None
    # False when the delivery must stay redeliverable (failed, not decided).
    final: bool = True


class Debouncer:
    """Admits one run per key within a window; the clock is injectable."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._seen: dict[tuple[str, int, str], float] = {}

    def admit(self, key: tuple[str, int, str], window_seconds: float) -> bool:
        now = self._clock()
        last = self._seen.get(key)
        if last is not None and now - last < window_seconds:
            return False
        self._seen[key] = now
        if len(self._seen) > _DEBOUNCE_PRUNE_AT:
            self._seen = {
                item: at
                for item, at in self._seen.items()
                if now - at < _DEBOUNCE_HORIZON
            }
        return True


def enabled_providers(env: Mapping[str, str]) -> tuple[Provider, ...]:
    names = {
        item.strip().lower() for item in env.get(WEBHOOK_PROVIDERS_ENV, "").split(",")
    }
    return tuple(provider for provider in PROVIDERS if provider in names)


class WebhookGateway:
    def __init__(
        self,
        *,
        env: Mapping[str, str],
        sources: ConfigSources,
        jobs: JobStore,
        client: SpecialistClient,
        services_factory: Callable[[InvocationRequest, str], dict[str, Any]],
        model_factory: ModelFactory | None = None,
        secrets: SecretProvider | None = None,
        deduper: DeliveryDeduper | None = None,
        debouncer: Debouncer | None = None,
        inflight: InFlightRegistry | None = None,
    ) -> None:
        self._env = dict(env)
        self._sources = sources
        self._jobs = jobs
        self._client = client
        self._services_factory = services_factory
        self._factory = model_factory
        self._secrets = secrets
        self._deduper = deduper or DeliveryDeduper()
        self._debouncer = debouncer or Debouncer()
        # Process-local unless the server passes a shared registry.
        self._inflight = inflight or InFlightRegistry(MemorySessionStore())

    @property
    def max_body_bytes(self) -> int:
        return max_webhook_bytes(self._env)

    def handle(
        self, provider: Provider, headers: Mapping[str, str], raw: bytes
    ) -> WebhookResponse:
        secret = self._secret(provider)
        if secret is None or not _verify(provider, headers, raw, secret):
            return WebhookResponse(
                401, {"detail": "invalid webhook signature"}, final=False
            )
        payload = _json_object(raw)
        if payload is None:
            return WebhookResponse(
                400, {"detail": "body must be a JSON object"}, final=False
            )
        try:
            event = _parse(provider, headers, payload)
        except (TypeError, ValueError):
            return WebhookResponse(
                400, {"detail": "webhook payload could not be read"}, final=False
            )
        if event is None:
            return _ignored("unsupported event")
        if event.delivery_id and self._deduper.is_recorded(event.delivery_id):
            return WebhookResponse(200, {"status": "duplicate"})
        response = self._route(event)
        if event.delivery_id and response.final:
            self._deduper.record(event.delivery_id)
        return response

    def _route(self, event: WebhookEvent) -> WebhookResponse:
        try:
            effective = self._effective(event.project)
        except ConfigError:
            return WebhookResponse(
                503,
                {
                    "status": "unavailable",
                    "reason": "organisation configuration is invalid",
                },
                final=False,
            )
        config = effective.config
        bot = config.vcs.bot_username
        if not bot:
            return WebhookResponse(
                202,
                {
                    "status": "ignored",
                    "reason": "vcs.bot_username is not configured for this project",
                },
                final=False,
            )
        decision = decide_trigger(
            event,
            bot_username=bot,
            on_push=config.trigger.on_push,
            allowed_commenters=config.trigger.allowed_commenters,
            events=config.trigger.events,
            skip_labels=config.trigger.skip_labels,
            skip_draft=config.trigger.skip_draft,
            skip_wip_titles=config.trigger.skip_wip_titles,
            skip_bot_authors=config.trigger.skip_bot_authors,
            allowed_assigners=config.trigger.allowed_assigners,
        )
        if not decision.run or decision.intent is None:
            return _ignored(decision.reason)
        window = config.trigger.debounce_seconds
        key = (event.project, event.number, event.head_sha)
        if decision.intent == "help":
            if not self._debouncer.admit(key, window):
                return _ignored(
                    "debounced: the same change was handled within the window"
                )
            return self._accept_help(event)
        flight = _flight_key(event)
        if not self._inflight.try_acquire(flight):
            return _ignored(
                "already in flight: this change and head are being reviewed"
            )
        if not self._debouncer.admit(key, window):
            self._inflight.release(flight)
            return _ignored("debounced: the same change was handled within the window")
        return self._accept(event, decision.intent, flight)

    def _accept(
        self, event: WebhookEvent, intent: Intent, flight: str
    ) -> WebhookResponse:
        request = _request_for(event, intent)
        job_id = uuid.uuid4().hex
        self._jobs.create(job_id)
        only: tuple[str, ...] | None = ("dwight",) if intent == "sec_review" else None
        return WebhookResponse(
            202,
            {"status": "accepted", "job_id": job_id},
            job=partial(self._run_flight_job, job_id, request, only, flight),
        )

    def _run_flight_job(
        self,
        job_id: str,
        request: InvocationRequest,
        only: Sequence[str] | None,
        flight: str,
    ) -> None:
        try:
            self._run_job(job_id, request, only)
        finally:
            self._inflight.release(flight)

    def _accept_help(self, event: WebhookEvent) -> WebhookResponse:
        request = _request_for(event, "help")
        job_id = uuid.uuid4().hex
        self._jobs.create(job_id)
        return WebhookResponse(
            202,
            {"status": "accepted", "job_id": job_id},
            job=partial(self._run_help, job_id, event, request),
        )

    def _run_help(
        self, job_id: str, event: WebhookEvent, request: InvocationRequest
    ) -> None:
        self._jobs.update(job_id, "running")
        text = _help_text(self._env.get(DOCS_URL_ENV))
        try:
            services = self._services_factory(request, "michael")
            gate = PostingGate.from_request(request)
            if services.get("posting_allowed") is False:
                gate = PostingGate(post_allowed=False)
            try:
                gate.require_write("help")
            except DryRunError:
                logger.info(
                    "help comment withheld by dry-run", extra={"agent": "michael"}
                )
                self._jobs.update(
                    job_id, "done", {"status": "help", "posted": False, "text": text}
                )
                return
            _post_help(services.get("vcs"), event, text)
        except Exception:
            logger.error(
                "webhook help failed",
                extra={"agent": "michael", "invocation_id": job_id},
            )
            self._jobs.update(job_id, "failed")
            return
        self._jobs.update(job_id, "done", {"status": "help", "posted": True})

    def _run_job(
        self, job_id: str, request: InvocationRequest, only: Sequence[str] | None
    ) -> None:
        self._jobs.update(job_id, "running")
        started = time.perf_counter()
        try:
            services = self._services_factory(request, "michael")
            spec = get_spec("michael")
            plan = plan_run(spec, services)
            if plan.disabled:
                result = disabled_result(spec, services)
            else:
                orchestrator = Orchestrator(
                    client=self._client, model_factory=self._factory
                )
                result = orchestrator.run(
                    request,
                    services,
                    post_override=plan.post_override,
                    only_agents=only,
                )
        except Exception as exc:
            logger.error(
                "webhook job failed",
                extra={
                    "agent": "michael",
                    "invocation_id": job_id,
                    "error_type": type(exc).__name__,
                },
            )
            self._jobs.update(job_id, "failed")
            return
        _finish(result, time.perf_counter() - started)
        self._jobs.update(job_id, "done", result.model_dump(mode="json"))

    def _effective(self, project: str) -> EffectiveConfig:
        org = load_org(self._sources)
        registry = load_registry(self._sources)
        return resolve(
            project,
            org=org,
            registry=registry,
            repo_config_text=None,
            call_overrides=None,
            bootstrap_env=self._env,
        )

    def _secret(self, provider: Provider) -> str | None:
        name = f"{provider}-webhook-secret"
        directory = self._env.get(WEBHOOK_SECRETS_DIR_ENV)
        if directory:
            try:
                return (Path(directory) / name).read_text(
                    encoding="utf-8"
                ).strip() or None
            except OSError:
                return None
        try:
            secrets = self._secrets or build_secret_provider(
                SquadConfig.model_validate(load_org(self._sources)).secrets, self._env
            )
            return secrets.get(name) or None
        except (ConfigError, SecretNotFoundError, SecretNameError, OSError, ValueError):
            return None


def max_webhook_bytes(env: Mapping[str, str]) -> int:
    raw = env.get(MAX_WEBHOOK_BYTES_ENV, "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_WEBHOOK_BYTES
    except ValueError:
        return DEFAULT_MAX_WEBHOOK_BYTES
    return value if value > 0 else DEFAULT_MAX_WEBHOOK_BYTES


def register_webhook_routes(
    app: FastAPI, gateway: WebhookGateway, providers: Sequence[Provider]
) -> None:
    for provider in providers:
        app.add_api_route(
            f"/webhooks/{provider}",
            _endpoint(gateway, provider),
            methods=["POST"],
            name=f"webhook_{provider}",
        )


def _endpoint(
    gateway: WebhookGateway, provider: Provider
) -> Callable[[Request, BackgroundTasks], Any]:
    async def receive(request: Request, background: BackgroundTasks) -> JSONResponse:
        raw = await _read_limited(request, gateway.max_body_bytes)
        if raw is None:
            return JSONResponse(
                status_code=413,
                content={"detail": "webhook body exceeds the size limit"},
            )
        outcome = await run_in_threadpool(
            gateway.handle, provider, dict(request.headers), raw
        )
        if outcome.job is not None:
            background.add_task(outcome.job)
        return JSONResponse(status_code=outcome.status, content=outcome.body)

    return receive


async def _read_limited(request: Request, limit: int) -> bytes | None:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _flight_key(event: WebhookEvent) -> str:
    return f"{event.provider}:{event.project}#{event.number}@{event.head_sha or 'none'}"


def _help_text(docs_url: str | None) -> str:
    if not docs_url:
        return HELP_TEXT
    return f"{HELP_TEXT}\n\nDocumentation: {docs_url}"


def _post_help(provider: Any, event: WebhookEvent, text: str) -> None:
    if provider is None:
        raise ValueError("no change request provider is configured for help")
    if event.kind == "issue":
        provider.comment_on_issue(event.project, event.number, text)
    else:
        provider.post_summary(ChangeRequestRef(event.project, event.number), text)


def _ignored(reason: str) -> WebhookResponse:
    return WebhookResponse(202, {"status": "ignored", "reason": reason})


def _verify(
    provider: Provider, headers: Mapping[str, str], raw: bytes, secret: str
) -> bool:
    if provider == "gitlab":
        return verify_gitlab(headers, secret)
    return verify_github(headers, raw, secret)


def _json_object(raw: bytes) -> dict[str, Any] | None:
    try:
        loaded: Any = json.loads(raw)
    except ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _parse(
    provider: Provider, headers: Mapping[str, str], payload: dict[str, Any]
) -> WebhookEvent | None:
    if provider == "gitlab":
        return parse_gitlab_event(headers, payload)
    return parse_github_event(headers, payload)


def _request_for(event: WebhookEvent, intent: Intent) -> InvocationRequest:
    if intent == "help":
        prompt = f"Show command help on item {event.number} in project {event.project}."
    elif intent in _REVIEW_INTENTS:
        prompt = (
            f"Review change request {event.number} in project {event.project} "
            f"({event.action or 'event'})."
        )
    else:
        prompt = f"Implement work item {event.number} in project {event.project}."
    key = f"{event.project}#{event.number}@{event.head_sha or 'none'}"
    return InvocationRequest(
        prompt=prompt,
        project=event.project,
        target=str(event.number),
        mode=_MODES.get(intent, Mode.REVIEW),
        post=True,
        idempotency_key=key[:_IDEMPOTENCY_LIMIT],
    )


def _finish(result: InvocationResult, duration: float) -> None:
    record_result(result, duration)
    logger.info(
        "webhook job finished",
        extra={
            "agent": result.agent,
            "status": result.status.value,
            "duration_ms": round(duration * 1000),
        },
    )
