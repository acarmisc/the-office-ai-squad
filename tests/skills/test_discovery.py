from __future__ import annotations

import pytest

from code_squad._common.skills.cache import SkillCache
from code_squad._common.skills.discovery import (
    DEFAULT_SKILL_PATHS,
    HEAD_REF_WARNING,
    discover_repo_skills,
    resolve_ref,
    search_paths,
    skill_files_changed,
)
from tests.skills.support import SHA_BASE, SHA_HEAD, FakeReader, skill_md


def test_each_subdirectory_with_skill_md_is_a_skill() -> None:
    reader = FakeReader(
        {
            SHA_BASE: {
                ".agents/skills/alpha/SKILL.md": skill_md("alpha"),
                ".agents/skills/beta/SKILL.md": skill_md("beta"),
                ".agents/skills/beta/notes.md": "not a skill file",
                ".agents/skills/deep/inner/SKILL.md": skill_md("too-deep"),
            }
        }
    )
    warnings: list[str] = []
    skills = discover_repo_skills(reader, ref=SHA_BASE, warnings=warnings)
    assert sorted(skill.name for skill in skills) == ["alpha", "beta"]
    assert all(skill.source == "repo" for skill in skills)
    assert skills[0].path == ".agents/skills/alpha/SKILL.md"
    assert warnings == []


def test_first_existing_candidate_path_wins() -> None:
    reader = FakeReader(
        {
            SHA_BASE: {
                ".claude/skills/from-claude/SKILL.md": skill_md("from-claude"),
                ".squad/skills/from-squad/SKILL.md": skill_md("from-squad"),
            }
        }
    )
    skills = discover_repo_skills(reader, ref=SHA_BASE)
    assert [skill.name for skill in skills] == ["from-claude"]


def test_existing_but_empty_candidate_still_wins_over_later_ones() -> None:
    reader = FakeReader(
        {
            SHA_BASE: {
                ".agents/skills/readme.md": "no subdirectories here",
                ".claude/skills/x/SKILL.md": skill_md("x"),
            }
        }
    )
    assert discover_repo_skills(reader, ref=SHA_BASE) == []


def test_configured_skills_repo_path_is_the_only_candidate() -> None:
    reader = FakeReader({SHA_BASE: {".agents/skills/a/SKILL.md": skill_md("a")}})
    paths = search_paths(DEFAULT_SKILL_PATHS, "custom/skills/")
    assert paths == ("custom/skills",)
    warnings: list[str] = []
    assert (
        discover_repo_skills(reader, paths=paths, ref=SHA_BASE, warnings=warnings) == []
    )
    assert warnings == ["skills path 'custom/skills' not found at ref"]


def test_missing_default_paths_are_silent() -> None:
    reader = FakeReader({SHA_BASE: {"README.md": "hi"}})
    warnings: list[str] = []
    assert discover_repo_skills(reader, ref=SHA_BASE, warnings=warnings) == []
    assert warnings == []


def test_unparseable_skill_file_is_reported_and_others_still_load() -> None:
    reader = FakeReader(
        {
            SHA_BASE: {
                ".agents/skills/good/SKILL.md": skill_md("good"),
                ".agents/skills/bad/SKILL.md": "no frontmatter at all",
            }
        }
    )
    warnings: list[str] = []
    skills = discover_repo_skills(reader, ref=SHA_BASE, warnings=warnings)
    assert [skill.name for skill in skills] == ["good"]
    assert warnings == [
        ".agents/skills/bad/SKILL.md: missing YAML frontmatter; skipped"
    ]


def test_default_reads_base_ref_and_never_requests_head() -> None:
    reader = FakeReader(
        {
            SHA_BASE: {".agents/skills/rules/SKILL.md": skill_md("rules", body="base")},
            SHA_HEAD: {".agents/skills/rules/SKILL.md": skill_md("rules", body="head")},
        }
    )
    ref, warnings = resolve_ref("base", SHA_BASE, SHA_HEAD)
    skills = discover_repo_skills(reader, ref=ref)
    assert warnings == []
    assert [skill.body for skill in skills] == ["base"]
    assert reader.refs_requested() == {SHA_BASE}


def test_head_mode_reads_head_and_warns() -> None:
    reader = FakeReader(
        {
            SHA_BASE: {".agents/skills/rules/SKILL.md": skill_md("rules", body="base")},
            SHA_HEAD: {".agents/skills/rules/SKILL.md": skill_md("rules", body="head")},
        }
    )
    ref, warnings = resolve_ref("head", SHA_BASE, SHA_HEAD)
    assert ref == SHA_HEAD
    assert warnings == [HEAD_REF_WARNING]
    assert HEAD_REF_WARNING == (
        "skills read from change request head (skills_ref=head); "
        "review rules may be modified by this change"
    )
    skills = discover_repo_skills(reader, ref=ref)
    assert [skill.body for skill in skills] == ["head"]
    assert reader.refs_requested() == {SHA_HEAD}


def test_skill_files_changed_in_change_request_are_flagged() -> None:
    changed = [
        ".agents/skills/rules/SKILL.md",
        ".agents/skills/rules/examples.md",
        "src/app.tsx",
        ".agents-old/skills/x.md",
        ".squad/skills",
    ]
    flagged = skill_files_changed(changed, DEFAULT_SKILL_PATHS)
    assert flagged == [
        ".agents/skills/rules/SKILL.md",
        ".agents/skills/rules/examples.md",
        ".squad/skills",
    ]


def test_cache_is_used_on_second_discovery_at_same_sha() -> None:
    reader = FakeReader({SHA_BASE: {".agents/skills/a/SKILL.md": skill_md("a")}})
    cache = SkillCache(clock=lambda: 0.0)
    first = discover_repo_skills(reader, ref=SHA_BASE, cache=cache, project="acme/web")
    reads_after_first = reader.calls("read_file")
    second = discover_repo_skills(reader, ref=SHA_BASE, cache=cache, project="acme/web")
    assert first == second
    assert reader.calls("read_file") == reads_after_first


def test_cache_requires_an_immutable_sha_ref() -> None:
    reader = FakeReader({"main": {}})
    with pytest.raises(ValueError, match="immutable commit SHA"):
        discover_repo_skills(reader, ref="main", cache=SkillCache())


def test_empty_ref_is_rejected() -> None:
    with pytest.raises(ValueError, match="repository ref is required"):
        discover_repo_skills(FakeReader({}), ref="")


@pytest.mark.parametrize("bad", ["../escape", "/abs/path", "a//b", "a/./b", "a\\b"])
def test_unsafe_skills_paths_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid skills path"):
        search_paths((), bad)
