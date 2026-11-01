"""Project registry: glob-matched entries and named profiles (brief 4.8, layer 3)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from code_squad._common.config.errors import ConfigError, problems_of
from code_squad._common.config.globs import glob_match, specificity
from code_squad._common.config.profiles import BUILTIN_PROFILES
from code_squad._common.config.schema import ProjectEntry, ProjectsFile, SquadFields
from code_squad._common.config.yaml_io import load_yaml

_LOG = logging.getLogger(__name__)
_REGISTRY_KEYS = ("match", "projects", "profiles")


def normalise_profile(raw: Mapping[str, Any], *, name: str) -> dict[str, Any]:
    """Validate a profile body and return only the keys it sets."""
    try:
        parsed = SquadFields.model_validate(dict(raw))
    except ValidationError as exc:
        raise ConfigError(f"profile {name!r} is invalid", problems_of(exc)) from exc
    return parsed.model_dump(mode="json", exclude_unset=True)


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    loaded = load_yaml(text, str(path))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return loaded


def _builtin_profiles() -> dict[str, dict[str, Any]]:
    return {name: dict(body) for name, body in BUILTIN_PROFILES.items()}


@dataclass
class ProjectRegistry:
    entries: list[ProjectEntry] = field(default_factory=list)
    profiles: dict[str, dict[str, Any]] = field(default_factory=_builtin_profiles)

    @classmethod
    def load(
        cls,
        source: Path | None,
        *,
        profiles_dir: Path | None = None,
    ) -> ProjectRegistry:
        """Load a projects file, or a directory of project files and profiles.

        Precedence for profiles, lowest first: built-ins, inline ``profiles:`` in
        project files, ``<source>/profiles/``, then ``profiles_dir``.
        """
        registry = cls(entries=[], profiles=_builtin_profiles())
        if source is not None and source.is_file():
            registry._absorb(_read_mapping(source), origin=str(source))
        elif source is not None and source.is_dir():
            for path in sorted([*source.glob("*.yaml"), *source.glob("*.yml")]):
                raw = _read_mapping(path)
                if any(key in raw for key in _REGISTRY_KEYS):
                    registry._absorb(raw, origin=str(path))
            registry._load_profile_dir(source / "profiles")
        if profiles_dir is not None:
            registry._load_profile_dir(profiles_dir)
        return registry

    def _absorb(self, raw: dict[str, Any], *, origin: str) -> None:
        if "match" in raw and "projects" not in raw and "profiles" not in raw:
            raw = {"projects": [raw]}
        try:
            parsed = ProjectsFile.model_validate(raw)
        except ValidationError as exc:
            raise ConfigError(f"{origin} is invalid", problems_of(exc)) from exc
        for name, body in parsed.profiles.items():
            self.profiles[name] = body.model_dump(mode="json", exclude_unset=True)
        self.entries.extend(parsed.projects)

    def _load_profile_dir(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        for path in sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")]):
            body = _read_mapping(path)
            self.profiles[path.stem] = normalise_profile(body, name=path.stem)

    def match(self, project: str) -> list[ProjectEntry]:
        """Matching entries, least specific first (later entries override earlier)."""
        matched = [entry for entry in self.entries if glob_match(entry.match, project)]
        return sorted(matched, key=lambda entry: specificity(entry.match))

    def profile(self, name: str) -> dict[str, Any]:
        try:
            return dict(self.profiles[name])
        except KeyError as exc:
            raise ConfigError(f"unknown profile {name!r}") from exc
