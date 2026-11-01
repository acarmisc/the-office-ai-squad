from __future__ import annotations

from code_squad.dwight.deps.model import Package
from code_squad.dwight.deps.parsers import parse_requirements, parse_uv_lock
from tests.dwight.helpers import fixture_text


def _by_name(packages: tuple[Package, ...]) -> dict[str, Package]:
    return {p.name: p for p in packages}


def test_requirements_pins_exact_versions_and_ignores_hashes_and_markers() -> None:
    result = parse_requirements("requirements.txt", fixture_text("requirements.txt"))
    found = _by_name(result.packages)
    assert found["requests"].version == "2.31.0"
    assert found["requests"].pinned is True
    assert found["requests"].line == 2
    assert found["pyyaml"].version == "6.0.1"
    assert found["flask"].version == "3.0.0"


def test_requirements_marks_ranges_and_bare_names_unpinned() -> None:
    result = parse_requirements("requirements.txt", fixture_text("requirements.txt"))
    found = _by_name(result.packages)
    assert found["urllib3"].pinned is False
    assert found["django"].version is None
    assert found["jinja2"].pinned is False


def test_requirements_warns_on_includes_and_editables() -> None:
    result = parse_requirements("requirements.txt", fixture_text("requirements.txt"))
    assert any("'-r'" in w for w in result.warnings)
    assert any("'-e'" in w for w in result.warnings)
    assert "base" not in {p.name for p in result.packages}


def test_uv_lock_skips_project_and_marks_direct_dependencies() -> None:
    result = parse_uv_lock("uv.lock", fixture_text("uv.lock"))
    found = _by_name(result.packages)
    assert "acme-api" not in found
    assert found["fastapi"].version == "0.115.0"
    assert found["fastapi"].direct is True
    assert found["pytest"].direct is True
    assert found["pyyaml"].direct is False
    assert found["pyyaml"].version == "6.0.2"


def test_uv_lock_rejects_invalid_toml() -> None:
    result = parse_uv_lock("uv.lock", "[[package]\n")
    assert result.packages == ()
    assert "invalid TOML" in result.warnings[0]
