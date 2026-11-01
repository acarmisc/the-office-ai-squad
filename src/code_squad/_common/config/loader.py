"""Layered configuration: defaults, org, registry, repository, call (brief 4.8).

Layers 2 and 3 are operator-controlled and are applied without restriction. Layers 4
and 5 are checked with ``merge.check_restricted``; a layer with any violation (or
invalid schema) is dropped as a whole, and the reason is recorded in
``EffectiveConfig.rejected_layers`` and ``warnings``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from code_squad._common.config.bootstrap import single_project_entry
from code_squad._common.config.errors import (
    ConfigError,
    ConfigUnreadableError,
    problems_of,
)
from code_squad._common.config.merge import Violation, check_restricted, merge_layers
from code_squad._common.config.projects import ProjectRegistry
from code_squad._common.config.schema import (
    ProjectEntry,
    RepoConfig,
    SquadConfig,
    SquadFields,
)
from code_squad._common.config.yaml_io import load_yaml
from code_squad._common.registry import AGENT_IDS

ENV_PREFIX: str = "SQUAD__"
DEFAULT_LAYER: str = "default"


@dataclass(frozen=True)
class ConfigSources:
    org_file: Path | None
    env: Mapping[str, str]
    projects_dir: Path | None
    profiles_dir: Path | None


@dataclass(frozen=True)
class RejectedLayer:
    layer: str
    violations: tuple[Violation, ...]


@dataclass(frozen=True)
class EffectiveConfig:
    config: SquadConfig
    provenance: dict[str, str]
    warnings: list[str]
    rejected_layers: list[RejectedLayer]
    config_hash: str
    project_key: str


@dataclass
class _Builder:
    merged: dict[str, Any]
    provenance: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    rejected: list[RejectedLayer] = field(default_factory=list)

    def apply(self, overlay: Mapping[str, Any], layer: str) -> None:
        _record(self.provenance, overlay, layer, "")
        self.merged = merge_layers(self.merged, overlay)

    def reject(self, layer: str, violations: list[Violation]) -> None:
        self.rejected.append(RejectedLayer(layer, tuple(violations)))
        detail = "; ".join(str(item) for item in violations)
        self.warnings.append(f"{layer} layer ignored: {detail}")

    def apply_checked(
        self, overlay: Mapping[str, Any], layer: str, kind: Literal["repo", "call"]
    ) -> bool:
        violations = check_restricted(self.merged, overlay, kind)
        if violations:
            self.reject(layer, violations)
            return False
        self.apply(overlay, layer)
        return True


def _defaults() -> dict[str, Any]:
    return SquadFields().model_dump(mode="json")


def _record(
    provenance: dict[str, str], node: Mapping[str, Any], layer: str, prefix: str
) -> None:
    for key, value in node.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            _record(provenance, value, layer, f"{path}.")
        else:
            provenance[path] = layer


def _parse_scalar(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text


def apply_env_overrides(raw: dict[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    """Apply ``SQUAD__SECTION__KEY`` variables on top of the org file contents."""
    for name in sorted(env):
        if not name.startswith(ENV_PREFIX):
            continue
        parts = name[len(ENV_PREFIX) :].lower().split("__")
        if any(part == "" for part in parts):
            raise ConfigError(f"{name}: empty path segment")
        node: dict[str, Any] = raw
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise ConfigError(f"{name}: {part} is set to a non-mapping value")
            node = child
        node[parts[-1]] = _parse_scalar(env[name])
    return raw


def load_org(sources: ConfigSources) -> dict[str, Any]:
    """Return the validated org layer: the org file overlaid with SQUAD__ variables."""
    raw: dict[str, Any] = {}
    path = sources.org_file
    if path is not None and path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigUnreadableError(
                f"cannot read org config {path}: {exc}"
            ) from exc
        loaded = load_yaml(text, f"org config {path}")
        if loaded is not None:
            if not isinstance(loaded, dict):
                raise ConfigError(f"org config {path} must be a mapping")
            raw = loaded
    raw = apply_env_overrides(raw, sources.env)
    try:
        SquadConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError("org config is invalid", problems_of(exc)) from exc
    return raw


def load_registry(sources: ConfigSources) -> ProjectRegistry:
    return ProjectRegistry.load(sources.projects_dir, profiles_dir=sources.profiles_dir)


def _entry_overlay(entry: ProjectEntry, registry: ProjectRegistry) -> dict[str, Any]:
    overlay: dict[str, Any] = {}
    if entry.extends is not None:
        overlay = merge_layers(overlay, registry.profile(entry.extends))
    overlay = merge_layers(
        overlay, entry.overrides.model_dump(mode="json", exclude_unset=True)
    )
    vcs: dict[str, Any] = {}
    if entry.provider is not None:
        vcs["provider"] = entry.provider
    if entry.base_url is not None:
        vcs["base_url"] = entry.base_url
    if entry.auth is not None:
        vcs["auth"] = entry.auth.model_dump(mode="json", exclude_none=True)
    if vcs:
        overlay = merge_layers(overlay, {"vcs": vcs})
    return overlay


def _apply_repo(builder: _Builder, text: str, registry: ProjectRegistry) -> None:
    layer = "repo"
    try:
        loaded = load_yaml(text, "repo config")
    except ConfigError as exc:
        builder.warnings.append(f"{exc}; the repo config was ignored")
        return
    if loaded is None:
        return
    if not isinstance(loaded, dict):
        builder.warnings.append("repo config must be a mapping and was ignored")
        return
    try:
        parsed = RepoConfig.model_validate(loaded)
    except ValidationError as exc:
        builder.reject(layer, _schema_violations(exc))
        return
    own_dump = parsed.model_dump(mode="json", exclude_unset=True)
    own_dump.pop("extends", None)
    if parsed.extends is None:
        builder.apply_checked(own_dump, layer, "repo")
        return
    if parsed.extends not in registry.profiles:
        builder.reject(
            layer, [Violation("extends", f"unknown profile {parsed.extends!r}")]
        )
        return
    profile = registry.profile(parsed.extends)
    combined = merge_layers(profile, own_dump)
    violations = check_restricted(builder.merged, combined, "repo")
    if violations:
        builder.reject(layer, violations)
        return
    builder.apply(profile, f"profile:{parsed.extends}")
    builder.apply(own_dump, layer)


def resolve(
    project: str,
    *,
    org: dict[str, Any],
    registry: ProjectRegistry,
    repo_config_text: str | None,
    call_overrides: dict[str, Any] | None,
    bootstrap_env: Mapping[str, str] | None = None,
    today: date | None = None,
) -> EffectiveConfig:
    builder = _Builder(merged=_defaults())
    _record(builder.provenance, builder.merged, DEFAULT_LAYER, "")
    _ensure_valid(org, "org config")
    builder.apply(org, "org")

    matched = registry.match(project)
    for entry in matched:
        builder.apply(_entry_overlay(entry, registry), f"registry:{entry.match}")
        _ensure_valid(builder.merged, f"registry entry {entry.match!r}")
    if not matched and bootstrap_env is not None and project:
        fallback = single_project_entry(bootstrap_env, project)
        if fallback is not None:
            builder.apply(_entry_overlay(fallback, registry), "bootstrap")

    if repo_config_text is not None:
        _apply_repo(builder, repo_config_text, registry)
    if call_overrides:
        try:
            SquadFields.model_validate(call_overrides)
        except ValidationError as exc:
            builder.reject("call", _schema_violations(exc))
        else:
            builder.apply_checked(call_overrides, "call", "call")

    config = _ensure_valid(builder.merged, "effective config")
    config, expiry_warnings = _drop_expired_risks(config, today or date.today())
    builder.warnings.extend(expiry_warnings)
    known = set(AGENT_IDS) | {agent.id for agent in config.extra_agents}
    for agent_id in sorted(set(config.agents) - known):
        builder.warnings.append(
            f"agents.{agent_id} does not match a known agent and is ignored"
        )
    project_key = matched[-1].key if matched and matched[-1].key else project
    return EffectiveConfig(
        config=config,
        provenance=dict(sorted(builder.provenance.items())),
        warnings=builder.warnings,
        rejected_layers=builder.rejected,
        config_hash=config_hash(config),
        project_key=project_key,
    )


def _schema_violations(exc: ValidationError) -> list[Violation]:
    out: list[Violation] = []
    for error in exc.errors():
        path = ".".join(str(part) for part in error["loc"])
        out.append(Violation(path, f"schema: {error['msg']}"))
    return out


def _ensure_valid(merged: dict[str, Any], what: str) -> SquadConfig:
    try:
        return SquadConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(f"{what} is invalid", problems_of(exc)) from exc


def _drop_expired_risks(
    config: SquadConfig, today: date
) -> tuple[SquadConfig, list[str]]:
    warnings: list[str] = []
    active = []
    for risk in config.security.accepted_risks:
        if risk.expires < today:
            warnings.append(
                f"accepted risk {risk.id} expired on {risk.expires} and is ignored"
            )
        else:
            active.append(risk)
    if len(active) == len(config.security.accepted_risks):
        return config, warnings
    security = config.security.model_copy(update={"accepted_risks": active})
    return config.model_copy(update={"security": security}), warnings


def config_hash(config: SquadConfig) -> str:
    canonical = json.dumps(
        config.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def repo_config_ref(
    effective: EffectiveConfig | SquadConfig | None,
    change_request_target_branch: str,
    head_sha: str,
    *,
    requested: Literal["base", "head"] = "base",
) -> str:
    """Branch or SHA to read ``.squad/config.yml`` from.

    The target branch unless the request asks for ``head`` and the org allows it
    (``repo_config.allow_head_ref``).
    """
    if requested != "head":
        return change_request_target_branch
    config = effective.config if isinstance(effective, EffectiveConfig) else effective
    if config is None or not config.repo_config.allow_head_ref:
        return change_request_target_branch
    if not head_sha:
        raise ValueError("head_sha is required when reading repo config from head")
    return head_sha
