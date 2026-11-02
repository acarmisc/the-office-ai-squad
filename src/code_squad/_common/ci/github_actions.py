"""One pull request, one agent, inside a GitHub Actions job (``squad ci review``).

The job reads the pull request from ``GITHUB_EVENT_PATH``, builds the services from the
job's ``GITHUB_TOKEN`` through the single-project bootstrap path (``VCS_PROVIDER``,
``VCS_BASE_URL``, ``VCS_TOKEN``) and runs the agent through the shared invocation path.
Nothing is served over HTTP. The job never checks out the pull request: the workspace
holds only what the workflow put there.

Repository skills come from the base branch through the provider. ``--skills-path``
adds skills from the local workspace as payload skills, which take precedence; point it
at a trusted shared-skills checkout, never at the pull request head.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Final

from code_squad._common.config.loader import ConfigSources
from code_squad._common.contract import (
    InvocationResult,
    Posted,
    RunStatus,
    SkillPayload,
    Stats,
    Verdict,
)
from code_squad._common.execute import (
    InvocationRefused,
    Invoker,
    ServicesFactory,
    execute_invocation,
    with_extra_knowledge,
)
from code_squad._common.model import ModelFactory
from code_squad._common.services import ProviderFactory, ServiceBuilder
from code_squad._common.skills.model import Skill, SkillLimits
from code_squad._common.skills.parse import parse_skill_md
from code_squad._common.skills.validate import enforce_limits
from code_squad._common.validation import ValidationFailure
from code_squad.michael.inprocess import InProcessSpecialistClient
from code_squad.michael.orchestrator import make_invoker

CI_AGENTS: Final = ("michael", "jim", "angela", "dwight", "darryl")
DEFAULT_AGENT: Final = "jim"
MICHAEL: Final = "michael"
PULL_REQUEST_EVENTS: Final = frozenset({"pull_request", "pull_request_target"})
DEFAULT_API_URL: Final = "https://api.github.com"
SKILL_GLOB: Final = "*/SKILL.md"
SKILL_FILE_MAX_BYTES: Final = 256 * 1024
_LOCAL: Final = "local"


class FailOn(StrEnum):
    NONE = "none"
    REQUEST_CHANGES = "request_changes"
    INCOMPLETE = "incomplete"


class CiUsageError(Exception):
    """The job cannot run as configured: missing input, credentials or a bad event."""


@dataclass(frozen=True)
class ReviewOptions:
    agent: str = DEFAULT_AGENT
    post: bool = False
    skills_path: str | None = None
    model: str | None = None
    fail_on: FailOn = FailOn.NONE
    result_file: Path = Path("squad-result.json")
    event_path: Path | None = None


@dataclass(frozen=True)
class PullRequest:
    number: int
    draft: bool
    head_repo: str | None
    base_repo: str | None

    @property
    def is_fork(self) -> bool:
        if not self.head_repo or not self.base_repo:
            return True
        return self.head_repo.lower() != self.base_repo.lower()


@dataclass(frozen=True)
class ReviewOutcome:
    """``result`` is None when the pull request was skipped; ``skipped`` says why."""

    result: InvocationResult | None
    skipped: str | None = None
    skills: tuple[str, ...] = ()


def run_review(
    options: ReviewOptions,
    env: Mapping[str, str],
    *,
    provider_factory: ProviderFactory | None = None,
    model_factory: ModelFactory | None = None,
) -> ReviewOutcome:
    _check_agent(options.agent)
    _check_event_name(env.get("GITHUB_EVENT_NAME"))
    event_path = options.event_path or _path_or_none(env.get("GITHUB_EVENT_PATH"))
    if event_path is None:
        raise CiUsageError(
            "GITHUB_EVENT_PATH is not set; run this in a pull request job"
        )
    pull = read_pull_request(event_path)
    if pull.draft:
        return ReviewOutcome(None, skipped="the pull request is a draft; no review ran")
    llm_key = env.get("LLM_API_KEY", "")
    if pull.is_fork and not llm_key:
        return ReviewOutcome(
            None,
            skipped="fork pull request: forks get no secrets, so no review ran",
        )
    if env.get("GITHUB_ACTOR") in _SECRETLESS_ACTORS and not llm_key:
        return ReviewOutcome(
            None,
            skipped="Dependabot pull request: repository secrets are not available "
            "to it (add LLM_API_KEY as a Dependabot secret to review these)",
        )
    repository = _required(env, "GITHUB_REPOSITORY")
    token = _required(env, "GITHUB_TOKEN")
    if not env.get("LLM_BASE_URL", "").strip() or not llm_key:
        raise CiUsageError("LLM_BASE_URL and LLM_API_KEY must be set")
    api_url = (env.get("GITHUB_API_URL") or DEFAULT_API_URL).rstrip("/")
    run_env = bootstrap_env(env, api_url, token)
    skills, notes = load_injected_skills(
        options.skills_path, _path_or_none(env.get("GITHUB_WORKSPACE"))
    )
    raw = request_payload(pull.number, repository, options, env, skills)
    services = _services_factory(run_env, provider_factory)
    invoker = _invoker_for(options.agent, services, model_factory)
    try:
        result = execute_invocation(
            options.agent,
            raw,
            services_factory=services,
            model_factory=model_factory,
            invoker=invoker,
        )
    except ValidationFailure as exc:
        raise CiUsageError("invalid request: " + "; ".join(exc.errors)) from exc
    except InvocationRefused as exc:
        raise CiUsageError(f"request refused: {exc}") from exc
    except Exception as exc:
        result = failed_result(options.agent, exc)
    if notes:
        result = result.model_copy(update={"warnings": [*notes, *result.warnings]})
    return ReviewOutcome(result, skills=tuple(item.name for item in skills))


_SECRETLESS_ACTORS: Final = frozenset({"dependabot[bot]"})


def failed_result(agent: str, exc: BaseException) -> InvocationResult:
    """A failed result instead of a traceback, so the job always gets a result file."""
    return InvocationResult(
        agent=agent,
        status=RunStatus.FAILED,
        verdict=Verdict.INCOMPLETE,
        summary="The review could not run; see warnings.",
        stats=Stats(),
        posted=Posted(),
        warnings=[f"run failed: {type(exc).__name__}"],
    )


def read_pull_request(path: Path) -> PullRequest:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CiUsageError(f"cannot read the event payload {path}") from exc
    pr: Any = data.get("pull_request") if isinstance(data, dict) else None
    if not isinstance(pr, dict):
        raise CiUsageError("the event is not a pull request event")
    number = pr.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise CiUsageError("the pull request event has no pull request number")
    return PullRequest(
        number=number,
        draft=pr.get("draft") is True,
        head_repo=_repo_full_name(pr, "head"),
        base_repo=_repo_full_name(pr, "base"),
    )


def bootstrap_env(env: Mapping[str, str], api_url: str, token: str) -> dict[str, str]:
    """A copy of the environment with the single-project VCS bootstrap variables set."""
    values = dict(env)
    values["VCS_PROVIDER"] = "github"
    values["VCS_BASE_URL"] = api_url
    values["VCS_TOKEN"] = token
    return values


def request_payload(
    number: int,
    repository: str,
    options: ReviewOptions,
    env: Mapping[str, str],
    skills: Sequence[SkillPayload],
) -> dict[str, Any]:
    run_id = env.get("GITHUB_RUN_ID") or _LOCAL
    attempt = env.get("GITHUB_RUN_ATTEMPT") or "1"
    raw: dict[str, Any] = {
        "prompt": f"Review change request {number} in project {repository}.",
        "project": repository,
        "target": str(number),
        "mode": "review",
        "post": options.post,
        "idempotency_key": f"gha-{run_id}-{attempt}-{options.agent}",
        "skills": [skill.model_dump(mode="json") for skill in skills],
    }
    if options.model:
        raw["model"] = options.model
    return raw


def load_injected_skills(
    relative: str | None, workspace: Path | None
) -> tuple[list[SkillPayload], list[str]]:
    """Read ``*/SKILL.md`` under ``relative`` in the workspace as payload skills."""
    if not relative:
        return [], []
    if workspace is None:
        raise CiUsageError("--skills-path needs GITHUB_WORKSPACE")
    root = workspace.resolve()
    target = _inside_workspace(root, relative)
    if not target.is_dir():
        raise CiUsageError(
            f"skills path {relative!r} is not a directory in the workspace"
        )
    notes: list[str] = []
    skills: list[Skill] = []
    for candidate in sorted(target.glob(SKILL_GLOB)):
        display = candidate.relative_to(root).as_posix()
        skill = _read_skill(candidate, root, display, notes)
        if skill is not None:
            skills.append(skill)
    limited = enforce_limits(skills, SkillLimits(), notes)
    payloads = [
        SkillPayload(name=item.name, description=item.description, body=item.body)
        for item in limited
    ]
    return payloads, notes


def gate_exit_code(result: InvocationResult, fail_on: FailOn) -> int:
    """0 when the result passes the gate, 1 when it fails. Failed runs always fail."""
    if result.status is RunStatus.FAILED:
        return 1
    if fail_on is FailOn.NONE:
        return 0
    if result.verdict is Verdict.REQUEST_CHANGES:
        return 1
    if fail_on is FailOn.INCOMPLETE and (
        result.status is not RunStatus.COMPLETE or result.verdict is Verdict.INCOMPLETE
    ):
        return 1
    return 0


def write_result(path: Path, result: InvocationResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _read_skill(
    candidate: Path, root: Path, display: str, notes: list[str]
) -> Skill | None:
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        notes.append(f"{display}: resolves outside the workspace; skipped")
        return None
    try:
        if resolved.stat().st_size > SKILL_FILE_MAX_BYTES:
            notes.append(
                f"{display}: larger than {SKILL_FILE_MAX_BYTES} bytes; skipped"
            )
            return None
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        notes.append(f"{display}: not readable as UTF-8 text; skipped")
        return None
    skill, warnings = parse_skill_md(text, path=display, source="repo")
    notes.extend(warnings)
    return skill


def _inside_workspace(root: Path, relative: str) -> Path:
    if PurePosixPath(relative).is_absolute() or PureWindowsPath(relative).is_absolute():
        raise CiUsageError("--skills-path must be relative to the workspace")
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise CiUsageError(f"--skills-path {relative!r} resolves outside the workspace")
    return target


def _services_factory(
    run_env: dict[str, str], provider_factory: ProviderFactory | None
) -> ServicesFactory:
    config_sources = ConfigSources(
        org_file=_path_or_none(run_env.get("SQUAD_CONFIG_FILE")),
        env=run_env,
        projects_dir=_path_or_none(run_env.get("SQUAD_PROJECTS_DIR")),
        profiles_dir=_path_or_none(run_env.get("SQUAD_PROFILES_DIR")),
    )
    builder = ServiceBuilder(
        provider_factory=provider_factory,
        config_sources=config_sources,
        env=run_env,
    )
    return with_extra_knowledge(builder.build)


def _invoker_for(
    agent: str, services: ServicesFactory, model_factory: ModelFactory | None
) -> Invoker | None:
    if agent != MICHAEL:
        return None
    return make_invoker(InProcessSpecialistClient(services, model_factory))


def _check_agent(agent: str) -> None:
    if agent not in CI_AGENTS:
        allowed = ", ".join(CI_AGENTS)
        raise CiUsageError(
            f"agent {agent!r} is not available in CI; use one of: {allowed}"
        )


def _check_event_name(name: str | None) -> None:
    if name and name not in PULL_REQUEST_EVENTS:
        raise CiUsageError(
            f"event {name!r} is not a pull request event; use pull_request"
        )


def _repo_full_name(pr: Mapping[str, Any], side: str) -> str | None:
    branch: Any = pr.get(side)
    repo: Any = branch.get("repo") if isinstance(branch, dict) else None
    full_name: Any = repo.get("full_name") if isinstance(repo, dict) else None
    return full_name if isinstance(full_name, str) and full_name else None


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise CiUsageError(f"{name} is not set")
    return value


def _path_or_none(value: str | None) -> Path | None:
    return Path(value) if value else None
