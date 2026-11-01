from __future__ import annotations

from code_squad.dwight.deps.model import Package
from code_squad.dwight.deps.parsers import parse_dockerfile
from tests.dwight.helpers import fixture_text


def _by_name(packages: tuple[Package, ...]) -> dict[str, Package]:
    return {p.name: p for p in packages}


def test_multi_stage_dockerfile_substitutes_args_and_skips_stage_refs() -> None:
    result = parse_dockerfile("Dockerfile", fixture_text("Dockerfile"))
    found = _by_name(result.packages)
    assert set(found) == {"docker.io/library/node", "nginx", "alpine"}
    node = found["docker.io/library/node"]
    assert node.version == "20.11-alpine"
    assert node.pinned is True
    assert node.line == 4


def test_digest_pins_the_image_and_latest_is_unpinned() -> None:
    result = parse_dockerfile("Dockerfile", fixture_text("Dockerfile"))
    found = _by_name(result.packages)
    assert found["nginx"].version.startswith("sha256:")  # type: ignore[union-attr]
    assert found["nginx"].pinned is True
    assert found["alpine"].version is None
    assert found["alpine"].pinned is False
    assert any("alpine" in w for w in result.warnings)


def test_unresolved_arg_is_reported_not_guessed() -> None:
    result = parse_dockerfile("Dockerfile", "FROM ${UNKNOWN}/app:1.2\n")
    package = result.packages[0]
    assert package.version is None
    assert package.pinned is False
    assert "unresolved ARG" in result.warnings[0]


def test_registry_port_is_not_mistaken_for_a_tag() -> None:
    result = parse_dockerfile("Dockerfile", "FROM localhost:5000/app\n")
    assert result.packages[0].name == "localhost:5000/app"
    assert result.packages[0].pinned is False
    result = parse_dockerfile("Dockerfile", "FROM localhost:5000/app:1.2\n")
    assert result.packages[0].name == "localhost:5000/app"
    assert result.packages[0].version == "1.2"


def test_platform_flag_and_alias_are_handled() -> None:
    text = "FROM --platform=linux/amd64 python:3.12-slim AS base\nFROM base AS app\n"
    result = parse_dockerfile("Dockerfile", text)
    assert [p.name for p in result.packages] == ["python"]
    assert result.packages[0].version == "3.12-slim"
