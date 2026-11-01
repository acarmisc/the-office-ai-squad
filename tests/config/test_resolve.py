from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from code_squad._common.config.errors import ConfigError
from code_squad._common.config.loader import (
    ConfigSources,
    EffectiveConfig,
    load_org,
    load_registry,
    repo_config_ref,
    resolve,
)
from code_squad._common.config.projects import ProjectRegistry
from code_squad._common.config.schema import SquadConfig
from tests.config.support import (
    TODAY,
    empty_registry,
    org_from,
    registry_from,
    run,
    write,
)

ORG_TEXT = """
review:
  max_findings: 10
"""


def _rejected(effective: EffectiveConfig) -> list[str]:
    return [layer.layer for layer in effective.rejected_layers]


def test_defaults_only_resolve_to_the_schema_defaults(tmp_path: Path) -> None:
    effective = run(org=org_from(None, tmp_path))
    assert effective.config == SquadConfig()
    assert set(effective.provenance.values()) == {"default"}
    assert effective.rejected_layers == []
    assert effective.warnings == []


def test_precedence_runs_org_registry_repo_call_in_order(tmp_path: Path) -> None:
    registry = registry_from(
        tmp_path,
        """
projects:
  - match: acme/web-shop
    overrides:
      review:
        max_findings: 20
""",
    )
    org = org_from(ORG_TEXT, tmp_path)
    repo = "review:\n  max_findings: 25\n"
    call = {"review": {"max_findings": 5}}

    assert (
        run(org=org, registry=registry, repo=repo, call=call).config.review.max_findings
        == 5
    )
    effective = run(org=org, registry=registry, repo=repo, call=call)
    assert effective.provenance["review.max_findings"] == "call"
    assert run(org=org, registry=registry, repo=repo).config.review.max_findings == 25
    assert (
        run(org=org, registry=registry, repo=repo).provenance["review.max_findings"]
        == "repo"
    )
    assert run(org=org, registry=registry).config.review.max_findings == 20
    assert (
        run(org=org, registry=registry).provenance["review.max_findings"]
        == "registry:acme/web-shop"
    )
    assert run(org=org).config.review.max_findings == 10
    assert run(org=org).provenance["review.max_findings"] == "org"
    assert run().config.review.max_findings == 30


def test_provenance_names_the_layer_for_each_key(tmp_path: Path) -> None:
    registry = registry_from(
        tmp_path,
        """
projects:
  - match: acme/*
    provider: github
""",
    )
    org = org_from("agents:\n  dwight:\n    model: sonnet-5-5\n", tmp_path)
    effective = run(org=org, registry=registry, repo="review:\n  chunking: truncate\n")
    assert effective.provenance["vcs.provider"] == "registry:acme/*"
    assert effective.provenance["agents.dwight.model"] == "org"
    assert effective.provenance["review.chunking"] == "repo"
    assert effective.provenance["review.max_findings"] == "default"


def test_profile_keys_are_attributed_to_the_profile(tmp_path: Path) -> None:
    effective = run(org=org_from(None, tmp_path), repo="extends: strict\n")
    assert effective.provenance["review.min_confidence_to_publish"] == "profile:strict"
    assert effective.config.review.min_confidence_to_publish == "low"


def test_config_hash_is_stable_and_tracks_changes(tmp_path: Path) -> None:
    org = org_from(None, tmp_path)
    first = run(org=org)
    again = run(org=org)
    changed = run(org=org, repo="review:\n  max_findings: 7\n")
    assert first.config_hash == again.config_hash
    assert re.fullmatch(r"[0-9a-f]{16}", first.config_hash)
    assert changed.config_hash != first.config_hash


# ---------- invalid repo input


def test_invalid_repo_yaml_is_a_warning_and_falls_back(tmp_path: Path) -> None:
    org = org_from(ORG_TEXT, tmp_path)
    effective = run(org=org, repo="review: [unclosed\n")
    assert effective.config.review.max_findings == 10
    assert _rejected(effective) == []
    assert any("not valid YAML" in w for w in effective.warnings)


def test_repo_that_is_not_a_mapping_is_ignored_with_a_warning(tmp_path: Path) -> None:
    effective = run(org=org_from(None, tmp_path), repo="- just\n- a list\n")
    assert effective.config == SquadConfig()
    assert any("must be a mapping" in w for w in effective.warnings)


def test_repo_schema_error_rejects_the_whole_layer(tmp_path: Path) -> None:
    effective = run(
        org=org_from(ORG_TEXT, tmp_path),
        repo="review:\n  max_findings: 3\n  not_a_key: true\n",
    )
    assert _rejected(effective) == ["repo"]
    assert effective.config.review.max_findings == 10
    assert "Extra inputs" in effective.warnings[0] or "schema" in effective.warnings[0]


def test_empty_repo_file_is_harmless(tmp_path: Path) -> None:
    effective = run(org=org_from(ORG_TEXT, tmp_path), repo="")
    assert effective.config.review.max_findings == 10
    assert effective.rejected_layers == []


# ---------- whole-layer rejection


REPO_VIOLATIONS: dict[str, str] = {
    "approve_mode_more_permissive": "vcs:\n  approve_mode: approve\n",
    "request_changes_turned_off": (
        "review:\n  verdict:\n    request_changes_on_blocker: false\n"
    ),
    "add_egress_host": "security:\n  allowed_hosts: [api.osv.dev, exfil.example]\n",
    "add_tool_to_allowlist": (
        "agents:\n  dwight:\n    tool_allowlist: [read_file, search_repo]\n"
    ),
    "disable_floor_rule": "agents:\n  dwight:\n    disabled_rules: [SEC-SECRETS-001]\n",
    "budget_above_limits": "agents:\n  dwight:\n    budgets:\n      tokens: 500000\n",
    "change_vcs_base_url": "vcs:\n  base_url: https://evil.example\n",
    "secret_outside_patterns": "vcs:\n  auth:\n    token_secret: Prod.Token\n",
    "skills_ref_head": "skills:\n  ref: head\n",
    "enable_writes_under_forced_dry_run": "posting:\n  force_dry_run: false\n",
}


@pytest.mark.parametrize("name", sorted(REPO_VIOLATIONS))
def test_repo_violation_drops_the_whole_layer(tmp_path: Path, name: str) -> None:
    org = org_from(
        "posting:\n  force_dry_run: true\n"
        "agents:\n  dwight:\n    tool_allowlist: [read_file, finish]\n" + ORG_TEXT,
        tmp_path,
    )
    repo = REPO_VIOLATIONS[name] + "routing:\n  fan_out_concurrency: 2\n"
    effective = run(org=org, repo=repo)
    assert _rejected(effective) == ["repo"], name
    assert effective.config.routing.fan_out_concurrency == 4, (
        "benign key must not apply"
    )
    assert any(w.startswith("repo layer ignored") for w in effective.warnings)


def test_violation_message_names_the_key(tmp_path: Path) -> None:
    effective = run(
        org=org_from(None, tmp_path),
        repo="agents:\n  dwight:\n    disabled_rules: [SEC-INJ-002]\n",
    )
    message = " ".join(effective.warnings)
    assert "agents.dwight.disabled_rules" in message
    assert "SEC-INJ-002" in message


def test_org_forced_dry_run_is_kept_when_repo_restates_it(tmp_path: Path) -> None:
    org = org_from("posting:\n  force_dry_run: true\n", tmp_path)
    effective = run(org=org, repo="posting:\n  force_dry_run: true\n")
    assert effective.config.posting.force_dry_run is True
    assert effective.rejected_layers == []


def test_valid_tightening_repo_applies(tmp_path: Path) -> None:
    effective = run(
        org=org_from(ORG_TEXT, tmp_path),
        repo=(
            "review:\n  min_confidence_to_publish: low\n"
            "trigger:\n  allowed_commenters: []\n"
            "implementer:\n  protected_paths: [infra/**]\n"
        ),
    )
    assert effective.rejected_layers == []
    assert effective.config.review.min_confidence_to_publish == "low"
    assert "infra/**" in effective.config.implementer.protected_paths


CALL_VIOLATIONS: dict[str, dict[str, Any]] = {
    "enable_writes": {"posting": {"force_dry_run": False}},
    "add_egress_host": {"security": {"allowed_hosts": ["exfil.example"]}},
    "add_tool": {"agents": {"dwight": {"tool_allowlist": ["publish_review"]}}},
    "disable_floor": {"agents": {"dwight": {"disabled_rules": ["SEC-XSS-001"]}}},
    "raise_budget": {"agents": {"dwight": {"budgets": {"tool_calls": 9000}}}},
    "change_base_url": {"vcs": {"base_url": "https://evil.example"}},
    "bad_secret": {"llm": {"api_key_secret": "Not.Allowed"}},
    "skills_head": {"skills": {"ref": "head"}},
    "approve_more_permissive": {"vcs": {"approve_mode": "approve"}},
}


@pytest.mark.parametrize("name", sorted(CALL_VIOLATIONS))
def test_call_overrides_follow_the_same_rules(tmp_path: Path, name: str) -> None:
    org = org_from("posting:\n  force_dry_run: true\n" + ORG_TEXT, tmp_path)
    call = {**CALL_VIOLATIONS[name], "review": {"max_findings": 2}}
    effective = run(org=org, call=call)
    assert _rejected(effective) == ["call"], name
    assert effective.config.review.max_findings == 10


def test_call_with_unknown_key_is_rejected(tmp_path: Path) -> None:
    effective = run(org=org_from(None, tmp_path), call={"bogus": {"x": 1}})
    assert _rejected(effective) == ["call"]


def test_valid_call_override_applies_last(tmp_path: Path) -> None:
    effective = run(
        org=org_from(ORG_TEXT, tmp_path),
        call={"review": {"max_findings": 4}},
    )
    assert effective.config.review.max_findings == 4
    assert effective.provenance["review.max_findings"] == "call"


# ---------- extends


def test_repo_extends_a_builtin_profile(tmp_path: Path) -> None:
    effective = run(org=org_from(None, tmp_path), repo="extends: lenient\n")
    assert effective.rejected_layers == []
    assert effective.config.review.min_severity_inline == "major"


def test_unknown_profile_rejects_the_repo_layer(tmp_path: Path) -> None:
    effective = run(org=org_from(None, tmp_path), repo="extends: nope\n")
    assert _rejected(effective) == ["repo"]
    assert "unknown profile" in " ".join(effective.warnings)


def test_a_profile_is_subject_to_the_same_tighten_only_rules(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    write(profiles, "loose.yaml", "vcs:\n  approve_mode: approve\n")
    org = org_from(None, tmp_path)
    registry = load_registry(ConfigSources(None, {}, None, profiles))
    effective = resolve(
        "acme/web-shop",
        org=org,
        registry=registry,
        repo_config_text="extends: loose\nreview:\n  max_findings: 2\n",
        call_overrides=None,
        today=TODAY,
    )
    assert _rejected(effective) == ["repo"]
    assert effective.config.review.max_findings == 30


def test_profile_file_overrides_builtin_by_name(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    write(profiles, "strict.yaml", "review:\n  max_findings: 12\n")
    registry = load_registry(ConfigSources(None, {}, None, profiles))
    effective = resolve(
        "acme/web-shop",
        org=org_from(None, tmp_path),
        registry=registry,
        repo_config_text="extends: strict\n",
        call_overrides=None,
        today=TODAY,
    )
    assert effective.config.review.max_findings == 12
    assert effective.config.review.min_confidence_to_publish == "medium"


# ---------- registry effects


def test_registry_entry_above_limits_fails_loudly(tmp_path: Path) -> None:
    registry = registry_from(
        tmp_path,
        """
projects:
  - match: acme/web-shop
    overrides:
      agents:
        dwight:
          budgets:
            tokens: 999999
""",
    )
    with pytest.raises(ConfigError, match="platform ceiling"):
        run(org=org_from(None, tmp_path), registry=registry)


def test_registry_entry_sets_provider_and_credentials(tmp_path: Path) -> None:
    registry = registry_from(
        tmp_path,
        """
projects:
  - match: platform/payments-api
    provider: gitlab
    base_url: https://gitlab.example.com
    auth:
      token_secret: gitlab-payments
    extends: strict
""",
    )
    effective = run(
        org=org_from(None, tmp_path), registry=registry, project="platform/payments-api"
    )
    assert effective.config.vcs.provider == "gitlab"
    assert effective.config.vcs.base_url == "https://gitlab.example.com"
    assert effective.config.vcs.auth.token_secret == "gitlab-payments"
    assert effective.config.security.offline_mode == "fail_incomplete"
    assert effective.project_key == "platform/payments-api"


def test_unknown_profile_in_registry_is_an_error(tmp_path: Path) -> None:
    registry = registry_from(
        tmp_path, "projects:\n  - match: acme/web-shop\n    extends: ghost\n"
    )
    with pytest.raises(ConfigError, match="unknown profile"):
        run(org=org_from(None, tmp_path), registry=registry)


# ---------- single-project fallback


def test_single_project_fallback_from_bootstrap_env(tmp_path: Path) -> None:
    effective = run(
        org=org_from(None, tmp_path),
        env={
            "VCS_PROVIDER": "github",
            "VCS_BASE_URL": "https://ghes.example.com/api/v3",
        },
    )
    assert effective.config.vcs.provider == "github"
    assert effective.config.vcs.base_url == "https://ghes.example.com/api/v3"
    assert effective.config.vcs.auth.token_secret == "vcs-token"
    assert effective.provenance["vcs.provider"] == "bootstrap"


def test_registry_match_takes_precedence_over_the_fallback(tmp_path: Path) -> None:
    registry = registry_from(
        tmp_path,
        "projects:\n  - match: acme/web-shop\n    provider: gitlab\n    base_url: https://g.example\n",
    )
    effective = run(
        org=org_from(None, tmp_path),
        registry=registry,
        env={"VCS_PROVIDER": "github", "VCS_BASE_URL": "https://api.github.com"},
    )
    assert effective.config.vcs.provider == "gitlab"


def test_fallback_needs_both_variables(tmp_path: Path) -> None:
    effective = run(org=org_from(None, tmp_path), env={"VCS_PROVIDER": "github"})
    assert effective.config.vcs.provider == "auto"


# ---------- accepted risks and agents


def test_expired_accepted_risks_are_dropped_with_a_warning(tmp_path: Path) -> None:
    org = org_from(
        """
security:
  accepted_risks:
    - id: CVE-2024-0001
      reason: Not reachable from the public API.
      expires: 2026-01-01
    - id: CVE-2026-0002
      reason: Mitigated at the gateway.
      expires: 2027-06-30
""",
        tmp_path,
    )
    effective = run(org=org)
    assert [risk.id for risk in effective.config.security.accepted_risks] == [
        "CVE-2026-0002"
    ]
    assert any("CVE-2024-0001 expired" in w for w in effective.warnings)


def test_unknown_agent_ids_are_warned_and_ignored(tmp_path: Path) -> None:
    effective = run(
        org=org_from(None, tmp_path), repo="agents:\n  toby:\n    enabled: false\n"
    )
    assert any("agents.toby" in w for w in effective.warnings)


def test_extra_agent_ids_are_known(tmp_path: Path) -> None:
    org = org_from(
        """
extra_agents:
  - id: oscar
    description: Python reviewer
    prompt_path: /p.md
""",
        tmp_path,
    )
    effective = run(org=org, repo="agents:\n  oscar:\n    enabled: true\n")
    assert not any("agents.oscar" in w for w in effective.warnings)


def test_invalid_org_fails_to_load(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="org config is invalid"):
        org_from("review:\n  max_findings: 0\n", tmp_path)


def test_registry_load_failure_is_a_config_error(tmp_path: Path) -> None:
    path = write(tmp_path, "projects.yaml", "projects:\n  - key: no-match-field\n")
    with pytest.raises(ConfigError):
        ProjectRegistry.load(path)


# ---------- repo config ref


def test_repo_config_is_read_from_the_target_branch_by_default() -> None:
    assert repo_config_ref(None, "main", "abc") == "main"


def test_head_is_used_only_when_requested_and_allowed(tmp_path: Path) -> None:
    denied = run(org=org_from(None, tmp_path))
    allowed = run(org=org_from("repo_config:\n  allow_head_ref: true\n", tmp_path))
    assert repo_config_ref(denied, "main", "abc123", requested="head") == "main"
    assert repo_config_ref(allowed, "main", "abc123", requested="head") == "abc123"
    assert repo_config_ref(allowed, "main", "abc123") == "main"


def test_head_ref_requires_a_sha() -> None:
    allowed = SquadConfig.model_validate({"repo_config": {"allow_head_ref": True}})
    with pytest.raises(ValueError, match="head_sha is required"):
        repo_config_ref(allowed, "main", "", requested="head")


# ---------- org layer via env


def test_env_variables_overlay_the_org_file(tmp_path: Path) -> None:
    path = write(tmp_path, "squad.yaml", "agents:\n  dwight:\n    model: haiku-5-5\n")
    org = load_org(
        ConfigSources(path, {"SQUAD__AGENTS__DWIGHT__MODEL": "sonnet-5-5"}, None, None)
    )
    effective = run(org=org)
    assert effective.config.agents["dwight"].model == "sonnet-5-5"
    assert effective.provenance["agents.dwight.model"] == "org"


def test_empty_registry_has_builtin_profiles() -> None:
    registry = empty_registry()
    assert {"strict", "balanced", "lenient"} <= set(registry.profiles)


# ---------------------------------------------------------------- hardened YAML


BILLION_LAUGHS = """
a: &a ["x","x","x","x","x","x","x","x","x"]
b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]
review: *b
"""


def test_repo_yaml_aliases_are_refused_with_a_warning(tmp_path: Path) -> None:
    effective = run(org=org_from(ORG_TEXT, tmp_path), repo=BILLION_LAUGHS)
    assert effective.config.review.max_findings == 10
    assert effective.rejected_layers == []
    assert any("aliases" in w for w in effective.warnings)


def test_oversized_repo_config_is_ignored(tmp_path: Path) -> None:
    big = "review:\n  ignore_globs:\n" + "".join(
        f"    - generated/{i}/**\n" for i in range(30000)
    )
    effective = run(org=org_from(ORG_TEXT, tmp_path), repo=big)
    assert effective.config.review.max_findings == 10
    assert any("larger than" in w for w in effective.warnings)


# ---------- routing.always_run


def test_repo_disabling_an_always_run_agent_drops_the_repo_layer(
    tmp_path: Path,
) -> None:
    effective = run(
        org=org_from(ORG_TEXT, tmp_path),
        repo="agents:\n  dwight:\n    enabled: false\nreview:\n  max_findings: 3\n",
    )
    assert _rejected(effective) == ["repo"]
    assert "dwight" not in effective.config.agents
    assert effective.config.review.max_findings == 10
    assert any("routing.always_run" in w for w in effective.warnings)


def test_call_disabling_an_always_run_agent_drops_the_call_layer(
    tmp_path: Path,
) -> None:
    effective = run(
        org=org_from(ORG_TEXT, tmp_path),
        call={"agents": {"dwight": {"enabled": False}}},
    )
    assert _rejected(effective) == ["call"]
    assert "dwight" not in effective.config.agents


def test_disabling_a_non_always_run_agent_applies_in_repo_and_call(
    tmp_path: Path,
) -> None:
    effective = run(
        org=org_from(ORG_TEXT, tmp_path),
        repo="agents:\n  jim:\n    enabled: false\n",
        call={"agents": {"michael": {"enabled": False}}},
    )
    assert effective.rejected_layers == []
    assert effective.config.agents["jim"].enabled is False
    assert effective.config.agents["michael"].enabled is False
