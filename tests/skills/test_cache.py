from __future__ import annotations

import pytest

from code_squad._common.skills.cache import SkillCache
from code_squad._common.skills.discovery import discover_repo_skills
from code_squad._common.skills.model import RootDiscovery
from tests.skills.support import SHA_BASE, SHA_HEAD, FakeReader, skill_md


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _reader(body: str = "v1") -> FakeReader:
    return FakeReader(
        {
            SHA_BASE: {".agents/skills/a/SKILL.md": skill_md("a", body=body)},
            SHA_HEAD: {".agents/skills/a/SKILL.md": skill_md("a", body="v2")},
        }
    )


def test_hit_returns_stored_value_without_reading_again() -> None:
    cache = SkillCache(clock=_Clock())
    value = RootDiscovery(found=True, warnings=("kept",))
    cache.put("acme/web", SHA_BASE, ".agents/skills", value)
    assert cache.get("acme/web", SHA_BASE, ".agents/skills") == value


def test_miss_on_unknown_key() -> None:
    cache = SkillCache(clock=_Clock())
    cache.put("acme/web", SHA_BASE, ".agents/skills", RootDiscovery(found=False))
    assert cache.get("acme/web", SHA_BASE, ".claude/skills") is None
    assert cache.get("other/project", SHA_BASE, ".agents/skills") is None
    assert cache.get("acme/web", SHA_HEAD, ".agents/skills") is None


def test_entry_expires_after_ttl() -> None:
    clock = _Clock()
    cache = SkillCache(ttl_seconds=600, clock=clock)
    cache.put("p", SHA_BASE, ".agents/skills", RootDiscovery(found=False))
    clock.now += 599
    assert cache.get("p", SHA_BASE, ".agents/skills") is not None
    clock.now += 1
    assert cache.get("p", SHA_BASE, ".agents/skills") is None
    assert len(cache) == 0


def test_discovery_uses_cache_and_rereads_after_ttl() -> None:
    clock = _Clock()
    reader = _reader()
    cache = SkillCache(ttl_seconds=600, clock=clock)
    discover_repo_skills(reader, ref=SHA_BASE, cache=cache, project="p")
    first_reads = reader.calls("read_file")
    discover_repo_skills(reader, ref=SHA_BASE, cache=cache, project="p")
    assert reader.calls("read_file") == first_reads
    clock.now += 601
    discover_repo_skills(reader, ref=SHA_BASE, cache=cache, project="p")
    assert reader.calls("read_file") == first_reads * 2


def test_new_sha_invalidates_by_key_and_reads_new_content() -> None:
    reader = _reader()
    cache = SkillCache(clock=_Clock())
    old = discover_repo_skills(reader, ref=SHA_BASE, cache=cache, project="p")
    new = discover_repo_skills(reader, ref=SHA_HEAD, cache=cache, project="p")
    assert [skill.body for skill in old] == ["v1"]
    assert [skill.body for skill in new] == ["v2"]
    assert SHA_HEAD in reader.refs_requested()


def test_cache_entries_are_scoped_per_project() -> None:
    reader = _reader()
    cache = SkillCache(clock=_Clock())
    discover_repo_skills(reader, ref=SHA_BASE, cache=cache, project="acme/web")
    reads = reader.calls("read_file")
    discover_repo_skills(reader, ref=SHA_BASE, cache=cache, project="acme/api")
    assert reader.calls("read_file") == reads * 2


def test_put_purges_expired_entries() -> None:
    clock = _Clock()
    cache = SkillCache(ttl_seconds=10, clock=clock)
    cache.put("p", SHA_BASE, "one", RootDiscovery(found=False))
    clock.now += 11
    cache.put("p", SHA_HEAD, "two", RootDiscovery(found=False))
    assert len(cache) == 1


@pytest.mark.parametrize("ttl", [0, -5])
def test_non_positive_ttl_is_rejected(ttl: float) -> None:
    with pytest.raises(ValueError, match="positive"):
        SkillCache(ttl_seconds=ttl)
