from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final, Literal, Protocol

from code_squad._common.skills.cache import SkillCache
from code_squad._common.skills.model import RootDiscovery, Skill
from code_squad._common.skills.parse import parse_skill_md

DEFAULT_SKILL_PATHS: Final[tuple[str, ...]] = (
    ".agents/skills",
    ".claude/skills",
    ".squad/skills",
)
HEAD_REF_WARNING: Final = (
    "skills read from change request head (skills_ref=head); "
    "review rules may be modified by this change"
)
_SKILL_FILE: Final = "SKILL.md"
_SHA: Final = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_PATH_MAX: Final = 256


class RepoReader(Protocol):
    """Read-only view of a repository at one ref.

    ``list_tree`` returns every file path under ``path`` (repository-relative,
    recursive) and raises ``FileNotFoundError`` when ``path`` is absent at ``ref``.
    ``read_file`` raises ``FileNotFoundError`` when the file does not exist at ``ref``.
    """

    def list_tree(self, path: str, ref: str) -> list[str]: ...

    def read_file(self, path: str, ref: str) -> str: ...


def search_paths(paths: Sequence[str], skills_repo_path: str | None) -> tuple[str, ...]:
    chosen = (skills_repo_path,) if skills_repo_path else tuple(paths)
    normalized = tuple(path.rstrip("/") for path in chosen)
    for path in normalized:
        _check_repo_path(path)
    return normalized


def discover_repo_skills(
    reader: RepoReader,
    *,
    paths: Sequence[str] = DEFAULT_SKILL_PATHS,
    ref: str,
    warnings: list[str] | None = None,
    cache: SkillCache | None = None,
    project: str = "",
) -> list[Skill]:
    """Return the skills of the first candidate path that exists at ``ref``.

    A single candidate path is treated as required: when it is missing a warning is
    recorded. With a cache, ``ref`` must be an immutable commit SHA.
    """
    if not ref:
        raise ValueError("a repository ref is required to read skills")
    if cache is not None and not _SHA.match(ref):
        raise ValueError("skill cache requires an immutable commit SHA ref")
    sink: list[str] = warnings if warnings is not None else []
    for path in paths:
        root = _load_root_cached(reader, path, ref, cache, project)
        sink.extend(root.warnings)
        if root.found:
            return list(root.skills)
    if len(paths) == 1:
        sink.append(f"skills path '{paths[0]}' not found at ref")
    return []


def load_root(reader: RepoReader, path: str, ref: str) -> RootDiscovery:
    try:
        files = reader.list_tree(path, ref)
    except FileNotFoundError:
        return RootDiscovery(found=False)
    skills: list[Skill] = []
    warnings: list[str] = []
    for skill_path in _skill_files(path, files):
        try:
            text = reader.read_file(skill_path, ref)
        except FileNotFoundError:
            warnings.append(f"{skill_path}: file not found at ref; skipped")
            continue
        skill, parse_warnings = parse_skill_md(text, path=skill_path)
        warnings.extend(parse_warnings)
        if skill is not None:
            skills.append(skill)
    return RootDiscovery(found=True, skills=tuple(skills), warnings=tuple(warnings))


def resolve_ref(
    skills_ref: Literal["base", "head"], base_ref: str, head_sha: str
) -> tuple[str, list[str]]:
    if skills_ref == "head":
        return head_sha, [HEAD_REF_WARNING]
    return base_ref, []


def skill_files_changed(
    changed_files: Sequence[str], paths: Sequence[str]
) -> list[str]:
    roots = tuple(path.rstrip("/") for path in paths)
    flagged = {
        changed
        for changed in changed_files
        for root in roots
        if changed == root or changed.startswith(f"{root}/")
    }
    return sorted(flagged)


def _load_root_cached(
    reader: RepoReader,
    path: str,
    ref: str,
    cache: SkillCache | None,
    project: str,
) -> RootDiscovery:
    if cache is not None:
        hit = cache.get(project, ref, path)
        if hit is not None:
            return hit
    root = load_root(reader, path, ref)
    if cache is not None:
        cache.put(project, ref, path, root)
    return root


def _skill_files(root: str, files: Sequence[str]) -> list[str]:
    prefix = f"{root}/"
    matches: list[str] = []
    for file_path in sorted(files):
        if not file_path.startswith(prefix):
            continue
        parts = file_path[len(prefix) :].split("/")
        if len(parts) == 2 and parts[1] == _SKILL_FILE and parts[0] not in ("", "."):
            matches.append(file_path)
    return matches


def _check_repo_path(path: str) -> None:
    parts = path.split("/")
    invalid = (
        not path
        or len(path) > _PATH_MAX
        or path.startswith("/")
        or any(part in ("", ".", "..") for part in parts)
        or "\\" in path
        or "\x00" in path
    )
    if invalid:
        raise ValueError(f"invalid skills path: {path!r}")
