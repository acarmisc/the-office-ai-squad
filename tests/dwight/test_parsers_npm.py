from __future__ import annotations

from code_squad.dwight.deps.model import Package, ParseResult
from code_squad.dwight.deps.parsers import (
    parse_file,
    parse_package_lock,
    parse_pnpm_lock,
    parse_yarn_lock,
)
from tests.dwight.helpers import fixture_text


def _by_name(result: ParseResult) -> dict[str, Package]:
    return {p.name: p for p in result.packages}


def test_package_lock_v3_uses_packages_map_and_nested_names() -> None:
    result = parse_package_lock(
        "package-lock.json", fixture_text("package-lock-v3.json")
    )
    found = _by_name(result)
    assert set(found) == {
        "@babel/core",
        "semver",
        "jest",
        "lodash",
        "unversioned-bundle",
    }
    assert found["@babel/core"].version == "7.20.0"
    assert found["@babel/core"].pinned is True
    assert found["@babel/core"].direct is True
    assert found["semver"].version == "6.3.1"
    assert found["semver"].direct is False
    assert found["jest"].direct is True


def test_package_lock_v3_flags_entries_without_version() -> None:
    result = parse_package_lock(
        "package-lock.json", fixture_text("package-lock-v3.json")
    )
    unpinned = _by_name(result)["unversioned-bundle"]
    assert unpinned.version is None
    assert unpinned.pinned is False
    assert any("unversioned-bundle" in w for w in result.warnings)


def test_package_lock_v1_reads_nested_dependencies_tree() -> None:
    result = parse_package_lock(
        "package-lock.json", fixture_text("package-lock-v1.json")
    )
    found = _by_name(result)
    assert found["express"].version == "4.17.1"
    assert found["accepts"].version == "1.3.7"
    assert found["@types/node"].version == "18.11.9"
    assert found["express"].direct is None


def test_package_lock_rejects_invalid_json() -> None:
    result = parse_package_lock("package-lock.json", "{not json")
    assert result.packages == ()
    assert "invalid JSON" in result.warnings[0]


def test_yarn_classic_entries_with_multiple_specs() -> None:
    result = parse_yarn_lock("yarn.lock", fixture_text("yarn-v1.lock"))
    found = _by_name(result)
    assert found["@babel/code-frame"].version == "7.12.13"
    assert found["@babel/code-frame"].line == 5
    assert found["lodash"].version == "4.17.21"
    assert len(result.packages) == 2


def test_yarn_berry_skips_metadata_and_workspace_entries() -> None:
    result = parse_yarn_lock("yarn.lock", fixture_text("yarn-berry.lock"))
    assert [p.name for p in result.packages] == ["lodash"]
    assert result.packages[0].version == "4.17.21"
    assert result.warnings == ()


def test_pnpm_v6_keys_strip_peer_suffix_and_mark_direct() -> None:
    result = parse_pnpm_lock("pnpm-lock.yaml", fixture_text("pnpm-v6.yaml"))
    found = _by_name(result)
    assert found["react-dom"].version == "18.2.0"
    assert found["jest"].version == "29.7.0"
    assert found["lodash"].direct is True
    assert found["jest"].direct is True
    assert found["@babel/core"].direct is False


def test_pnpm_v9_keys_without_slash_and_importers_direct_set() -> None:
    result = parse_pnpm_lock("pnpm-lock.yaml", fixture_text("pnpm-v9.yaml"))
    found = _by_name(result)
    assert set(found) == {"@babel/core", "lodash", "vitest"}
    assert found["@babel/core"].version == "7.24.0"
    assert found["vitest"].direct is True
    assert found["@babel/core"].direct is False


def test_pnpm_invalid_yaml_is_a_warning_not_an_error() -> None:
    result = parse_pnpm_lock("pnpm-lock.yaml", "packages: [unclosed")
    assert result.packages == ()
    assert "invalid YAML" in result.warnings[0]


def test_dispatcher_routes_npm_files_by_basename() -> None:
    result = parse_file("web/yarn.lock", fixture_text("yarn-berry.lock"))
    assert result.packages[0].source_file == "web/yarn.lock"
