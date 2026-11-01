from __future__ import annotations

from pathlib import Path

import pytest

from code_squad._common.config.errors import ConfigError
from code_squad._common.config.globs import glob_match, specificity
from code_squad._common.config.profiles import BUILTIN_PROFILES
from code_squad._common.config.projects import ProjectRegistry
from tests.config.support import org_from, registry_from, run, write


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    [
        ("**/*.tsx", "src/app/View.tsx", True),
        ("**/*.tsx", "View.tsx", True),
        ("**/*.tsx", "src/app/View.ts", False),
        ("src/**", "src/a/b/c.ts", True),
        ("src/*", "src/a/b/c.ts", False),
        ("src/*", "src/c.ts", True),
        (".github/workflows/**", ".github/workflows/ci.yml", True),
        ("**/payment*/**", "svc/payments-core/x.java", True),
        ("**/Dockerfile*", "deploy/Dockerfile.prod", True),
        ("acme/web-*", "acme/web-shop", True),
        ("acme/web-*", "acme/web", False),
        ("acme/web-*", "acme/web-shop/extra", False),
        ("a.b", "axb", False),
        ("file?.txt", "file1.txt", True),
        ("file?.txt", "file12.txt", False),
    ],
)
def test_glob_matching(pattern: str, path: str, matches: bool) -> None:
    assert glob_match(pattern, path) is matches


def test_specificity_orders_exact_then_fewer_wildcards_then_longer_prefix() -> None:
    keys = ["acme/**", "acme/*", "acme/web-*", "acme/web-shop"]
    ordered = sorted(keys, key=specificity)
    assert ordered == ["acme/**", "acme/*", "acme/web-*", "acme/web-shop"]


def test_match_returns_least_specific_first(tmp_path: Path) -> None:
    registry = registry_from(
        tmp_path,
        """
projects:
  - match: acme/web-shop
    provider: github
  - match: acme/web-*
    provider: gitlab
  - match: acme/*
    provider: github
""",
    )
    assert [entry.match for entry in registry.match("acme/web-shop")] == [
        "acme/*",
        "acme/web-*",
        "acme/web-shop",
    ]


def test_inheritance_lets_specific_entries_override_only_what_they_set(
    tmp_path: Path,
) -> None:
    registry = registry_from(
        tmp_path,
        """
projects:
  - match: acme/web-shop
    overrides:
      review:
        max_findings: 7
  - match: acme/*
    provider: gitlab
    base_url: https://gitlab.example.com
    overrides:
      review:
        max_findings: 50
        min_severity_inline: major
""",
    )
    effective = run(registry=registry, project="acme/web-shop")
    assert effective.config.vcs.provider == "gitlab"
    assert effective.config.vcs.base_url == "https://gitlab.example.com"
    assert effective.config.review.max_findings == 7
    assert effective.config.review.min_severity_inline == "major"
    assert effective.provenance["review.max_findings"] == "registry:acme/web-shop"
    assert effective.provenance["review.min_severity_inline"] == "registry:acme/*"


def test_profile_applies_before_the_entry_own_overrides(tmp_path: Path) -> None:
    registry = registry_from(
        tmp_path,
        """
profiles:
  custom:
    review:
      max_findings: 11
      min_severity_inline: major
projects:
  - match: acme/web-shop
    extends: custom
    overrides:
      review:
        max_findings: 4
""",
    )
    effective = run(registry=registry)
    assert effective.config.review.max_findings == 4
    assert effective.config.review.min_severity_inline == "major"


def test_a_glob_profile_then_exact_overrides_chain(tmp_path: Path) -> None:
    registry = registry_from(
        tmp_path,
        """
projects:
  - match: acme/*
    extends: strict
  - match: acme/web-shop
    extends: lenient
""",
    )
    effective = run(registry=registry)
    assert effective.config.review.min_severity_inline == "major"
    assert effective.config.security.offline_mode == "fail_incomplete"


def test_builtin_profiles_are_available_without_files() -> None:
    registry = ProjectRegistry()
    assert set(BUILTIN_PROFILES) == {"strict", "balanced", "lenient"}
    assert set(BUILTIN_PROFILES) <= set(registry.profiles)


def test_profile_file_overrides_builtin_and_is_validated(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    write(profiles, "lenient.yaml", "review:\n  max_findings: 9\n")
    registry = ProjectRegistry.load(None, profiles_dir=profiles)
    assert registry.profiles["lenient"] == {"review": {"max_findings": 9}}
    write(profiles, "broken.yaml", "review:\n  nope: 1\n")
    with pytest.raises(ConfigError, match="profile 'broken' is invalid"):
        ProjectRegistry.load(None, profiles_dir=profiles)


def test_directory_registry_reads_project_files_and_profile_subdir(
    tmp_path: Path,
) -> None:
    registry_dir = tmp_path / "projects"
    write(
        registry_dir, "payments.yaml", "match: platform/payments-api\nextends: strict\n"
    )
    write(registry_dir, "projects.yaml", "projects:\n  - match: acme/web-shop\n")
    write(registry_dir / "profiles", "team.yaml", "review:\n  max_findings: 3\n")
    write(registry_dir, "extra-agents.yaml", "extra_agents: []\n")
    registry = ProjectRegistry.load(registry_dir)
    assert {entry.match for entry in registry.entries} == {
        "platform/payments-api",
        "acme/web-shop",
    }
    assert "team" in registry.profiles


def test_invalid_registry_entry_is_reported(tmp_path: Path) -> None:
    path = write(
        tmp_path, "projects.yaml", "projects:\n  - match: x\n    provider: bitbucket\n"
    )
    with pytest.raises(ConfigError, match=r"projects.yaml|is invalid"):
        ProjectRegistry.load(path)


def test_unknown_key_in_registry_overrides_is_reported(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "projects.yaml",
        "projects:\n  - match: x\n    overrides:\n"
        "      vcs:\n        provdier: github\n",
    )
    with pytest.raises(ConfigError):
        ProjectRegistry.load(path)


def test_missing_registry_is_empty() -> None:
    registry = ProjectRegistry.load(None)
    assert registry.entries == []
    assert registry.match("anything") == []


def test_org_policy_still_applies_over_registry_defaults(tmp_path: Path) -> None:
    org = org_from("posting:\n  force_dry_run: true\n", tmp_path)
    registry = registry_from(tmp_path, "projects:\n  - match: acme/*\n    key: acme\n")
    effective = run(org=org, registry=registry)
    assert effective.config.posting.force_dry_run is True
    assert effective.project_key == "acme"
