from __future__ import annotations

import dataclasses
import importlib
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from code_squad._common.spec import AgentSpec

if TYPE_CHECKING:
    from code_squad._common.config.schema import ExtraAgent

AGENT_IDS: Final = ("michael", "jim", "angela", "dwight", "darryl", "pam")
ROLES: Final[dict[str, str]] = {
    "michael": "orchestrator",
    "jim": "react-reviewer",
    "angela": "java-reviewer",
    "dwight": "sec-reviewer",
    "darryl": "devops",
    "pam": "frontend-dev",
}


DEFAULT_EXTRA_MODEL: Final = "sonnet-5-5"
_EXTRA_TASK: Final = (
    "Review change request {target} in project {project}. Action: {action}."
)
_EXTRAS: dict[str, AgentSpec] = {}
_EXTRA_KNOWLEDGE: dict[str, tuple[str, ...]] = {}


class UnknownAgentError(KeyError):
    pass


class ExtraAgentError(ValueError):
    pass


def get_spec(name: str) -> AgentSpec:
    if name not in AGENT_IDS:
        if name in _EXTRAS:
            return _apply_env_overrides(_EXTRAS[name])
        raise UnknownAgentError(name)
    module = importlib.import_module(f"code_squad.{name}")
    spec = getattr(module, "SPEC", None)
    if not isinstance(spec, AgentSpec):
        raise TypeError(f"code_squad.{name} does not expose an AgentSpec as SPEC")
    return _apply_env_overrides(spec)


def all_specs() -> list[AgentSpec]:
    return [get_spec(name) for name in AGENT_IDS]


def _apply_env_overrides(spec: AgentSpec) -> AgentSpec:
    overrides: dict[str, Any] = {}
    if model_id := os.environ.get("AGENT_MODEL_ID"):
        overrides["model_id"] = model_id
    if (max_tokens := _env_int("AGENT_MAX_TOKENS", minimum=1)) is not None:
        overrides["max_tokens"] = max_tokens
    if (max_iterations := _env_int("AGENT_MAX_ITERATIONS", minimum=1)) is not None:
        overrides["max_iterations"] = max_iterations
    if (temperature := _env_temperature()) is not None:
        overrides["temperature"] = temperature
    return dataclasses.replace(spec, **overrides) if overrides else spec


def _env_int(name: str, *, minimum: int) -> int | None:
    raw = _raw_env(name)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_temperature() -> float | None:
    raw = _raw_env("AGENT_TEMPERATURE")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("AGENT_TEMPERATURE must be a number") from exc
    if not 0.0 <= value <= 2.0:
        raise ValueError("AGENT_TEMPERATURE must be between 0 and 2")
    return value


def _raw_env(name: str) -> str | None:
    raw = os.environ.get(name)
    return raw if raw else None


def register_extra_agents(extra: Sequence[ExtraAgent]) -> None:
    """Build specs for configuration-declared agents. Replaces any earlier registration.

    Tool sets come from the named preset only, so an extra agent can never gain an
    external write other than ``publish_review`` (which the posting gate still guards).
    """
    specs: dict[str, AgentSpec] = {}
    knowledge: dict[str, tuple[str, ...]] = {}
    for item in extra:
        if item.id in AGENT_IDS or item.id in specs:
            raise ExtraAgentError(f"extra agent id {item.id!r} is not unique")
        specs[item.id] = _extra_spec(item)
        knowledge[item.id] = tuple(item.knowledge_dirs)
    _EXTRAS.clear()
    _EXTRAS.update(specs)
    _EXTRA_KNOWLEDGE.clear()
    _EXTRA_KNOWLEDGE.update(knowledge)


def extra_agent_ids() -> tuple[str, ...]:
    return tuple(_EXTRAS)


def extra_knowledge_dirs(name: str) -> tuple[str, ...]:
    return _EXTRA_KNOWLEDGE.get(name, ())


def _extra_spec(item: ExtraAgent) -> AgentSpec:
    from code_squad._common.config.errors import ConfigError
    from code_squad._common.config.presets import preset_tools

    try:
        names = preset_tools(item.tool_preset)
    except ConfigError as exc:
        raise ExtraAgentError(str(exc)) from exc
    return AgentSpec(
        name=item.id,
        description=item.description,
        role="extra",
        system_prompt=_read_extra_prompt(item.id, item.prompt_path),
        task_template=_EXTRA_TASK,
        tools=_tools_for(names),
        model_id=item.model or DEFAULT_EXTRA_MODEL,
        input_key="prompt",
        modes=("review",),
    )


def _read_extra_prompt(agent: str, path: str) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ExtraAgentError(
            f"prompt file for extra agent {agent!r} cannot be read: {path}"
        ) from exc
    if not text.strip():
        raise ExtraAgentError(f"prompt file for extra agent {agent!r} is empty")
    return text


def _tools_for(names: tuple[str, ...]) -> tuple[Any, ...]:
    from code_squad._common.common_tools import finish, read_knowledge
    from code_squad._common.review_tools import (
        get_review_context,
        list_tree,
        publish_review,
        read_file,
        search_repo,
    )
    from code_squad._common.skills.tools import get_project_skills, load_skill

    available: dict[str, Any] = {
        "finish": finish,
        "read_knowledge": read_knowledge,
        "get_review_context": get_review_context,
        "read_file": read_file,
        "search_repo": search_repo,
        "list_tree": list_tree,
        "load_skill": load_skill,
        "get_project_skills": get_project_skills,
        "publish_review": publish_review,
    }
    return tuple(available[name] for name in names)
