from __future__ import annotations

import dataclasses
import importlib
import os
from typing import Any, Final

from code_squad._common.spec import AgentSpec

AGENT_IDS: Final = ("michael", "jim", "angela", "dwight", "darryl", "pam")
ROLES: Final[dict[str, str]] = {
    "michael": "orchestrator",
    "jim": "react-reviewer",
    "angela": "java-reviewer",
    "dwight": "sec-reviewer",
    "darryl": "devops",
    "pam": "frontend-dev",
}


class UnknownAgentError(KeyError):
    pass


def get_spec(name: str) -> AgentSpec:
    if name not in AGENT_IDS:
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
