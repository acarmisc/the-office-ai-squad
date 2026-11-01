from __future__ import annotations

import functools
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Final

from code_squad._common.contract import InvocationRequest, SkillPayload
from code_squad._common.skills.cache import SkillCache
from code_squad._common.skills.discovery import (
    DEFAULT_SKILL_PATHS,
    RepoReader,
    discover_repo_skills,
    search_paths,
    skill_files_changed,
)
from code_squad._common.skills.model import Skill, SkillLimits, SkillSet
from code_squad._common.skills.parse import skill_from_payload
from code_squad._common.skills.validate import enforce_limits, sanitize_text

JAVA_DISCOVERY_PATHS: Final[tuple[str, ...]] = DEFAULT_SKILL_PATHS
_JAVA_AGENT: Final = "angela"
_RANK: Final[dict[str, int]] = {"payload": 0, "repo": 1, "builtin": 2}


def default_paths_for(agent: str) -> tuple[str, ...]:
    return JAVA_DISCOVERY_PATHS if agent == _JAVA_AGENT else DEFAULT_SKILL_PATHS


def load_skills(
    *,
    payload: Sequence[SkillPayload],
    reader: RepoReader | None,
    ref: str,
    builtin: Sequence[Skill] = (),
    changed_files: Sequence[str] = (),
    agent: str,
    limits: SkillLimits | None = None,
    paths: Sequence[str] = DEFAULT_SKILL_PATHS,
    skills_repo_path: str | None = None,
    cache: SkillCache | None = None,
    project: str = "",
    ref_warnings: Sequence[str] = (),
) -> SkillSet:
    """Select the skills for one agent run.

    Precedence is payload > repo > builtin. A higher-precedence skill with the same name
    replaces the lower one (recorded in ``overrides``, not a warning). ``ref`` must be
    the commit the repository skills are read from; with a cache it must be a SHA.
    """
    warnings: list[str] = list(ref_warnings)
    search = search_paths(paths, skills_repo_path)
    repo: list[Skill] = []
    if reader is not None:
        repo = discover_repo_skills(
            reader,
            paths=search,
            ref=ref,
            warnings=warnings,
            cache=cache,
            project=project,
        )
    candidates = [
        *(skill_from_payload(item) for item in payload),
        *repo,
        *builtin,
    ]
    ordered = sorted(candidates, key=_precedence_key)
    eligible = [skill for skill in ordered if not skill.agents or agent in skill.agents]
    chosen, overrides = _resolve_names(eligible, warnings)
    changed = [_normal_path(path) for path in changed_files]
    selected = _select(chosen, changed, warnings)
    cleaned = [_clean(skill, warnings) for skill in selected]
    limited = enforce_limits(cleaned, limits or SkillLimits(), warnings)
    flagged = skill_files_changed(changed, search) if reader is not None else []
    return SkillSet(
        skills=tuple(limited),
        warnings=tuple(warnings),
        changed_in_change_request=tuple(flagged),
        overrides=tuple(overrides),
    )


def skillset_from_payload(request: InvocationRequest, agent: str) -> SkillSet:
    return load_skills(
        payload=request.skills,
        reader=None,
        ref="",
        agent=agent,
        project=request.project or "",
    )


@functools.lru_cache(maxsize=512)
def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob with ``**``, ``*`` and ``?`` into an anchored-at-start regex."""
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        else:
            char = pattern[index]
            parts.append({"*": "[^/]*", "?": "[^/]"}.get(char, re.escape(char)))
            index += 1
    return re.compile("".join(parts) + r"\Z")


def _precedence_key(skill: Skill) -> tuple[int, int, str]:
    return (_RANK[skill.source], -skill.priority, skill.name)


def _resolve_names(
    skills: Sequence[Skill], warnings: list[str]
) -> tuple[list[Skill], list[str]]:
    chosen: dict[str, Skill] = {}
    overrides: list[str] = []
    for skill in skills:
        winner = chosen.get(skill.name)
        if winner is None:
            chosen[skill.name] = skill
        elif winner.source == skill.source:
            warnings.append(
                f"skill {skill.name}: duplicate {skill.source} skill ignored"
            )
        else:
            overrides.append(f"{skill.name}: {winner.source} overrides {skill.source}")
    return list(chosen.values()), overrides


def _select(
    skills: Sequence[Skill], changed: Sequence[str], warnings: list[str]
) -> list[Skill]:
    selected: list[Skill] = []
    for skill in skills:
        if not skill.applies_to:
            selected.append(skill)
        elif not changed:
            warnings.append(
                f"skill {skill.name} not applied: applies_to is set but no changed "
                "files are known"
            )
        elif _matches_any(skill.applies_to, changed):
            selected.append(skill)
    return selected


def _matches_any(patterns: Sequence[str], paths: Sequence[str]) -> bool:
    return any(
        glob_to_regex(pattern).match(path) is not None
        for pattern in patterns
        for path in paths
    )


def _clean(skill: Skill, warnings: list[str]) -> Skill:
    body, body_warnings = sanitize_text(skill.body, skill=skill.name, field="body")
    description, desc_warnings = sanitize_text(
        skill.description, skill=skill.name, field="description"
    )
    warnings.extend(body_warnings)
    warnings.extend(desc_warnings)
    return replace(skill, body=body, description=description)


def _normal_path(path: str) -> str:
    stripped = path[2:] if path.startswith("./") else path
    return stripped.lstrip("/")
