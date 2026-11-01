from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from code_squad._common.config.loader import (
    ConfigSources,
    EffectiveConfig,
    load_org,
    load_registry,
    resolve,
)
from code_squad._common.config.projects import ProjectRegistry

TODAY: date = date(2026, 10, 31)


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def org_from(
    text: str | None, tmp: Path, env: dict[str, str] | None = None
) -> dict[str, Any]:
    path = write(tmp, "squad.yaml", text) if text is not None else None
    return load_org(ConfigSources(path, env or {}, None, None))


def run(
    *,
    org: dict[str, Any] | None = None,
    registry: ProjectRegistry | None = None,
    repo: str | None = None,
    call: dict[str, Any] | None = None,
    project: str = "acme/web-shop",
    env: dict[str, str] | None = None,
) -> EffectiveConfig:
    return resolve(
        project,
        org=org if org is not None else load_org(ConfigSources(None, {}, None, None)),
        registry=registry if registry is not None else ProjectRegistry(),
        repo_config_text=repo,
        call_overrides=call,
        bootstrap_env=env,
        today=TODAY,
    )


def registry_from(tmp: Path, text: str) -> ProjectRegistry:
    path = write(tmp, "projects.yaml", text)
    return ProjectRegistry.load(path)


def empty_registry() -> ProjectRegistry:
    return load_registry(ConfigSources(None, {}, None, None))
