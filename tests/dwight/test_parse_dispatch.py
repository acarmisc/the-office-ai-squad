from __future__ import annotations

import pytest

from code_squad.dwight.deps.parsers import is_manifest, parse_file


@pytest.mark.parametrize(
    "path",
    [
        "services/api/pom.xml",
        "web/package-lock.json",
        "web/yarn.lock",
        "web/pnpm-lock.yaml",
        "gradle.lockfile",
        "app/build.gradle.kts",
        "requirements-dev.txt",
        "requirements.txt",
        "uv.lock",
        "deploy/Dockerfile.prod",
        "deploy/api.Dockerfile",
    ],
)
def test_manifest_names_are_recognised(path: str) -> None:
    assert is_manifest(path)


@pytest.mark.parametrize(
    "path", ["src/app.ts", "README.md", "requirements.in", "x/Dockerfile.md.bak"]
)
def test_non_manifests_are_ignored(path: str) -> None:
    assert not is_manifest(path)


def test_unsupported_file_gives_a_warning_and_no_packages() -> None:
    result = parse_file("src/app.ts", "const x = 1;")
    assert result.packages == ()
    assert "not a supported" in result.warnings[0]
