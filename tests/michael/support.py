from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from code_squad._common.config.loader import ConfigSources
from code_squad._common.contract import (
    Finding,
    InvocationRequest,
    InvocationResult,
    RunStatus,
    Verdict,
)
from code_squad._common.secrets.base import SecretNotFoundError
from code_squad._common.services import ServiceBuilder
from code_squad._common.session import MemorySessionStore
from code_squad._common.vcs.fake import FakeVcsProvider
from code_squad.michael.fanout import SpecialistError
from code_squad.michael.gateway import MichaelWiring
from tests.agents.support import ENV, HEAD, NUMBER, PROJECT, REACT_PATH, react_provider
from tests.support import finding_dict

BOT = "code-squad-bot"
WEBHOOK_SECRET = "fake-webhook-secret-for-tests"
GITLAB_SECRET = "fake-gitlab-secret-for-tests"
ORG_YAML = "\n".join(
    [
        "vcs:",
        f"  bot_username: {BOT}",
        "trigger:",
        "  allowed_commenters: [alice]",
        "",
    ]
)


@dataclass(frozen=True)
class Call:
    agent: str
    payload: dict[str, Any]
    timeout_s: float
    idempotency_key: str
    trace_headers: dict[str, str]


Responder = (
    InvocationResult | BaseException | Callable[[dict[str, Any]], InvocationResult]
)


@dataclass
class FakeSpecialists:
    """Scripted specialist client. Records every call; responses are per agent."""

    responses: dict[str, Responder] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def bind(self, configured: Mapping[str, str]) -> FakeSpecialists:
        return self

    def invoke(
        self,
        agent: str,
        payload: dict[str, Any],
        *,
        timeout_s: float,
        idempotency_key: str,
        trace_headers: Mapping[str, str],
    ) -> InvocationResult:
        with self._lock:
            self.calls.append(
                Call(
                    agent,
                    dict(payload),
                    timeout_s,
                    idempotency_key,
                    dict(trace_headers),
                )
            )
        response = self.responses.get(agent)
        if response is None:
            raise SpecialistError(f"no response configured for {agent}")
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, InvocationResult):
            return response
        return response(payload)

    def agents(self) -> list[str]:
        return [call.agent for call in self.calls]

    def call_for(self, agent: str) -> Call:
        matches = [call for call in self.calls if call.agent == agent]
        assert len(matches) == 1, f"expected one call to {agent}, got {len(matches)}"
        return matches[0]


def result_for(
    agent: str,
    *,
    verdict: Verdict = Verdict.APPROVE,
    findings: Sequence[Finding] = (),
    status: RunStatus = RunStatus.COMPLETE,
    warnings: Sequence[str] = (),
) -> InvocationResult:
    return InvocationResult(
        agent=agent,
        status=status,
        verdict=verdict,
        summary=f"{agent} finished.",
        findings=list(findings),
        warnings=list(warnings),
    )


def make_finding(
    agent: str,
    *,
    file: str = REACT_PATH,
    start: int = 10,
    end: int = 10,
    severity: str = "major",
    confidence: str = "high",
    rule: str = "REACT-HOOKS-001",
    category: str = "correctness",
    title: str = "Stale response overwrites newer data",
    failure: str | None = None,
    head: str = HEAD,
) -> Finding:
    data = finding_dict(
        agent=agent,
        file=file,
        line_start=start,
        line_end=end,
        head_sha=head,
        rule_id=rule,
        category=category,
        severity=severity,
        confidence=confidence,
        title=title,
        rationale="The value can be stale when requests overlap.",
        failure_scenario=failure,
    )
    return Finding.model_validate(data).with_id()


class _Secrets:
    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = dict(values or {"vcs-token": "fake-token-for-tests"})

    def get(self, name: str) -> str:
        if name not in self._values:
            raise SecretNotFoundError(name)
        return self._values[name]


def builder_for(
    fake: FakeVcsProvider, tmp_path: Path, org: str | None = ORG_YAML
) -> ServiceBuilder:
    org_file: Path | None = None
    if org is not None:
        org_file = tmp_path / "squad.yaml"
        org_file.write_text(org, encoding="utf-8")
    return ServiceBuilder(
        provider_factory=lambda _settings: fake,
        secret_provider=_Secrets(),
        config_sources=ConfigSources(
            org_file=org_file, env={}, projects_dir=None, profiles_dir=None
        ),
        env=dict(ENV),
    )


def review_request(**overrides: Any) -> InvocationRequest:
    values: dict[str, Any] = {
        "prompt": "Review the change request.",
        "project": PROJECT,
        "target": str(NUMBER),
        "mode": "review",
        "post": True,
    }
    values.update(overrides)
    return InvocationRequest.model_validate(values)


def no_model(*_args: Any) -> Any:
    raise AssertionError("no model call is expected on this path")


def github_secrets() -> _Secrets:
    return _Secrets(
        {
            "vcs-token": "fake-token-for-tests",
            "github-webhook-secret": WEBHOOK_SECRET,
            "gitlab-webhook-secret": GITLAB_SECRET,
        }
    )


def webhook_client(
    tmp_path: Path,
    specialists: FakeSpecialists,
    fake: FakeVcsProvider | None = None,
    *,
    providers: str = "github,gitlab",
    org: str = ORG_YAML,
) -> tuple[TestClient, FakeVcsProvider]:
    from code_squad.server import create_app

    vcs = fake or react_provider()
    builder = builder_for(vcs, tmp_path, org)
    org_file = tmp_path / "squad.yaml"
    wiring = MichaelWiring(
        env={**ENV, "WEBHOOK_PROVIDERS": providers},
        config_sources=ConfigSources(
            org_file=org_file, env={}, projects_dir=None, profiles_dir=None
        ),
        secret_provider=github_secrets(),
        specialist_client=specialists,
    )
    app = create_app(
        "michael",
        model_factory=no_model,
        services_factory=builder.build,
        session_store=MemorySessionStore(),
        wiring=wiring,
    )
    return TestClient(app), vcs
