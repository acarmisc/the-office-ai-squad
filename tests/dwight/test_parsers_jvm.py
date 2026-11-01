from __future__ import annotations

from code_squad.dwight.deps.model import Package
from code_squad.dwight.deps.parsers import (
    parse_gradle_build,
    parse_gradle_lockfile,
    parse_pom,
)
from tests.dwight.helpers import fixture_text


def _by_name(packages: tuple[Package, ...]) -> dict[str, Package]:
    return {p.name: p for p in packages}


def test_pom_resolves_properties_and_dependency_management() -> None:
    result = parse_pom("pom.xml", fixture_text("pom.xml"))
    found = _by_name(result.packages)
    assert found["com.fasterxml.jackson.core:jackson-databind"].version == "2.15.3"
    assert found["org.apache.logging.log4j:log4j-core"].version == "2.17.1"
    assert found["junit:junit"].version == "4.13.2"
    assert found["junit:junit"].pinned is True


def test_pom_unresolved_property_and_range_are_unpinned_with_warnings() -> None:
    result = parse_pom("pom.xml", fixture_text("pom.xml"))
    found = _by_name(result.packages)
    spring = found["org.springframework:spring-core"]
    assert spring.version is None and spring.pinned is False
    postgres = found["org.postgresql:postgresql"]
    assert postgres.version is None and postgres.pinned is False
    assert any("spring-core" in w and "unresolved" in w for w in result.warnings)
    assert any("postgresql" in w and "range" in w for w in result.warnings)


def test_pom_rejects_doctype_declarations() -> None:
    xml = '<!DOCTYPE project [<!ENTITY x "y">]><project/>'
    result = parse_pom("pom.xml", xml)
    assert result.packages == ()
    assert "DOCTYPE" in result.warnings[0]


def test_pom_reports_malformed_xml() -> None:
    result = parse_pom("pom.xml", "<project><dependencies>")
    assert result.packages == ()
    assert "invalid XML" in result.warnings[0]


def test_gradle_lockfile_reads_coordinates_and_skips_empty_lines() -> None:
    result = parse_gradle_lockfile("gradle.lockfile", fixture_text("gradle.lockfile"))
    found = _by_name(result.packages)
    assert set(found) == {
        "com.fasterxml.jackson.core:jackson-databind",
        "org.apache.logging.log4j:log4j-core",
        "org.slf4j:slf4j-api",
    }
    assert found["org.slf4j:slf4j-api"].version == "2.0.9"
    assert found["org.slf4j:slf4j-api"].line == 6


def test_build_gradle_flags_dynamic_managed_and_property_versions() -> None:
    result = parse_gradle_build("build.gradle", fixture_text("build.gradle"))
    found = _by_name(result.packages)
    assert found["com.google.guava:guava"].version == "32.1.3-jre"
    assert found["junit:junit"].pinned is True
    assert found["org.apache.commons:commons-lang3"].version is None
    assert found["org.postgresql:postgresql"].version is None
    assert found["com.fasterxml.jackson.core:jackson-databind"].version is None
    assert "commented.out:not-a-dependency" not in found
    assert found["com.fasterxml.jackson:jackson-bom"].version == "2.15.3"
    assert found["org.springframework.boot:spring-boot-starter-web"].line == 6
    assert len(result.warnings) == 3


def test_build_gradle_kts_handles_kapt_and_kotlin_dsl() -> None:
    result = parse_gradle_build("build.gradle.kts", fixture_text("build.gradle.kts"))
    found = _by_name(result.packages)
    assert set(found) == {
        "io.ktor:ktor-server-core",
        "ch.qos.logback:logback-classic",
        "org.junit.jupiter:junit-jupiter",
        "com.google.dagger:dagger-compiler",
    }
    assert found["com.google.dagger:dagger-compiler"].version == "2.48"
    assert all(p.direct is True for p in result.packages)
    assert result.warnings == ()
