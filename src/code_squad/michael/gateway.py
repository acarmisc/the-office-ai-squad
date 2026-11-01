"""Webhook gateway for michael: GitLab and GitHub receivers with async orchestration.

Order of checks for each delivery: signature (401), JSON body (400), supported event
(202 ignored), delivery id already seen (200 duplicate), effective configuration
(503 when invalid), bot identity configured, trigger rules, debounce. Only then a job is
created and the response is 202 accepted; the orchestration runs after the response.

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
from code_squad._common.registry import get_spec
from code_squad._common.secrets.base import (
    SecretNameError,
    SecretNotFoundError,
    SecretProvider,
)
from code_squad._common.secrets.factory import build_secret_provider
from code_squad._common.services import disabled_result, plan_run
from code_squad._common.session import JobStore
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

    def handle(
        self, provider: Provider, headers: Mapping[str, str], raw: bytes
    ) -> WebhookResponse:
        secret = self._secret(provider)
        if secret is None or not _verify(provider, headers, raw, secret):
            return WebhookResponse(401, {"detail": "invalid webhook signature"})
        payload = _json_object(raw)
        if payload is None:
            return WebhookResponse(400, {"detail": "body must be a JSON object"})
        event = _parse(provider, headers, payload)
        if event is None:
            return _ignored("unsupported event")
        if event.delivery_id and self._deduper.seen(event.delivery_id):
            return WebhookResponse(200, {"status": "duplicate"})
        try:
            effective = self._effective(event.project)
        except ConfigError:
            return WebhookResponse(
                503,
                {
                    "status": "unavailable",
                    "reason": "organisation configuration is invalid",
                },
            )
        config = effective.config
        bot = config.vcs.bot_username
        if not bot:
            return _ignored("vcs.bot_username is not configured for this project")
        decision = decide_trigger(
            event,
            bot_username=bot,
            on_push=config.trigger.on_push,
            allowed_commenters=config.trigger.allowed_commenters,
            skip_labels=config.trigger.skip_labels,
            skip_draft=config.trigger.skip_draft,
        )
        if not decision.run or decision.intent is None:
            return _ignored(decision.reason)
        if decision.intent == "help":
            return _ignored("the help command is not available in this version")
        key = (event.project, event.number, event.head_sha)
        if not self._debouncer.admit(key, config.trigger.debounce_seconds):
            return _ignored("debounced: the same change was handled within the window")
        return self._accept(event, decision.intent)

    def _accept(self, event: WebhookEvent, intent: Intent) -> WebhookResponse:
        request = _request_for(event, intent)
        job_id = uuid.uuid4().hex
        self._jobs.create(job_id)
        only: tuple[str, ...] | None = ("dwight",) if intent == "sec_review" else None
        return WebhookResponse(
            202,
            {"status": "accepted", "job_id": job_id},
            job=partial(self._run_job, job_id, request, only),
        )

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
        except Exception:
            logger.error(
                "webhook job failed",
                extra={"agent": "michael", "invocation_id": job_id},
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
        raw = await request.body()
        outcome = await run_in_threadpool(
            gateway.handle, provider, dict(request.headers), raw
        )
        if outcome.job is not None:
            background.add_task(outcome.job)
        return JSONResponse(status_code=outcome.status, content=outcome.body)

    return receive


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
    if intent in _REVIEW_INTENTS:
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
