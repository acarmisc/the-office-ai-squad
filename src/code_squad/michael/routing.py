"""Deterministic routing: changed files and manifests to specialist agents.

Routes come from the effective configuration (``routing.routes``, which already contains
the defaults), extended by a few built-in content and path rules. A route with
``requires`` only applies when the stack it names is detected in the change or in the
repository manifests.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final

from code_squad._common.config.globs import glob_match
from code_squad._common.config.schema import ExtraAgent, Route, RoutingConfig

Rule = tuple[str, str, tuple[str, ...]]

_REACT_DEPS: Final = frozenset({"react", "next"})
_JAVA_BUILD_FILES: Final = frozenset(
    {"pom.xml", "settings.gradle", "settings.gradle.kts"}
)
_JAVA_SUFFIXES: Final = (".java", ".kt", ".kts")
_YAML_SUFFIXES: Final = (".yaml", ".yml")
_COMPOSE: Final = re.compile(r"^compose[^/]*\.ya?ml$")
_API_VERSION: Final = re.compile(r"^apiVersion:\s*\S", re.MULTILINE)
_KIND: Final = re.compile(r"^kind:\s*\S", re.MULTILINE)
_BUILTIN_ROUTES: Final[tuple[Rule, ...]] = (
    (".gitlab-ci.yml", "darryl", ()),
    (".github/workflows/**", "darryl", ()),
    ("**/Dockerfile*", "darryl", ()),
    ("**/compose*.yml", "darryl", ()),
    ("**/compose*.yaml", "darryl", ()),
    ("**/*.tf", "darryl", ()),
    ("charts/**", "darryl", ()),
    ("**/kustomization.yaml", "darryl", ()),
    ("**/kustomization.yml", "darryl", ()),
)
_KUBERNETES_REASON: Final = "Kubernetes manifest (apiVersion and kind present)"
_MAX_REASONS: Final = 20


@dataclass(frozen=True)
class RoutePlan:
    agents: tuple[str, ...]
    reasons: dict[str, list[str]] = field(default_factory=dict)
    ambiguous: bool = False
    stacks: tuple[str, ...] = ()


def detect_stack(
    changed_files: Sequence[str], manifests: Mapping[str, str]
) -> set[str]:
    stacks: set[str] = set()
    for path in [*changed_files, *manifests]:
        name = _basename(path)
        if path == ".gitlab-ci.yml" or path.startswith(".github/workflows/"):
            stacks.add("ci")
        if name.startswith("Dockerfile") or _COMPOSE.match(name):
            stacks.add("docker")
        if path.endswith(".tf"):
            stacks.add("iac")
        if path.endswith(_JAVA_SUFFIXES) or name in _JAVA_BUILD_FILES:
            stacks.add("java")
        if name.startswith("build.gradle"):
            stacks.add("java")
    if _react_dependencies(manifests.get("package.json")):
        stacks.add("react")
    if any(_is_kubernetes(path, text) for path, text in manifests.items()):
        stacks.add("k8s")
    return stacks


def route(
    changed_files: Sequence[str],
    manifests: Mapping[str, str],
    routing: RoutingConfig,
    extra_agents: Sequence[ExtraAgent] = (),
    *,
    disabled: Collection[str] = (),
) -> RoutePlan:
    stacks = detect_stack(changed_files, manifests)
    rules = _effective_rules(routing.routes)
    found: dict[str, list[str]] = {}
    specialist_hit = False
    for path in changed_files:
        for glob, agent, requires in rules:
            if glob_match(glob, path) and set(requires) <= stacks:
                _add(found, agent, f"{path} matches {glob}")
                specialist_hit = True
        for extra in extra_agents:
            if any(glob_match(pattern, path) for pattern in extra.routes):
                _add(found, extra.id, f"{path} matches an extra agent route")
                specialist_hit = True
        if path.endswith(_YAML_SUFFIXES) and _is_kubernetes(
            path, manifests.get(path, "")
        ):
            _add(found, "darryl", f"{path}: {_KUBERNETES_REASON}")
            specialist_hit = True
    for agent in routing.always_run:
        _add(found, agent, "always run")
    for agent in disabled:
        found.pop(agent, None)
    return RoutePlan(
        agents=tuple(found),
        reasons=found,
        ambiguous=bool(changed_files) and not specialist_hit,
        stacks=tuple(sorted(stacks)),
    )


def add_agents(
    plan: RoutePlan,
    agents: Sequence[str],
    *,
    reason: str,
    known: Collection[str],
    disabled: Collection[str] = (),
) -> RoutePlan:
    """Extend a plan with agents chosen outside the rules (for example a classifier)."""
    found: dict[str, list[str]] = {
        agent: list(items) for agent, items in plan.reasons.items()
    }
    for agent in agents:
        if agent in known and agent not in disabled:
            _add(found, agent, reason)
    return replace(plan, agents=tuple(found), reasons=found)


def _effective_rules(routes: Sequence[Route]) -> list[Rule]:
    rules: list[Rule] = [
        (item.glob, agent, tuple(item.requires))
        for item in routes
        for agent in item.agents
    ]
    known = {(glob, agent) for glob, agent, _ in rules}
    rules.extend(rule for rule in _BUILTIN_ROUTES if (rule[0], rule[1]) not in known)
    return rules


def _add(found: dict[str, list[str]], agent: str, reason: str) -> None:
    items = found.setdefault(agent, [])
    if reason not in items and len(items) < _MAX_REASONS:
        items.append(reason)


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _react_dependencies(text: str | None) -> bool:
    if not text:
        return False
    try:
        data: Any = json.loads(text)
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            deps.update(str(name) for name in section)
    return bool(deps & _REACT_DEPS)


def _is_kubernetes(path: str, text: str) -> bool:
    if not path.endswith(_YAML_SUFFIXES) or not text:
        return False
    return bool(_API_VERSION.search(text) and _KIND.search(text))
