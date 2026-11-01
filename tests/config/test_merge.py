from __future__ import annotations

from typing import Any

import pytest

from code_squad._common.config.merge import Layer, check_restricted, merge_layers
from code_squad._common.config.schema import SquadFields


def _base(**overrides: Any) -> dict[str, Any]:
    base = SquadFields().model_dump(mode="json")
    base["secrets"]["allowed_patterns"] = ["^[a-z0-9][a-z0-9._-]*$"]
    for path, value in overrides.items():
        node = base
        *parents, leaf = path.split("__")
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return base


def _reasons(
    base: dict[str, Any], overlay: dict[str, Any], layer: Layer = "repo"
) -> list[str]:
    return [str(v) for v in check_restricted(base, overlay, layer)]


# ---------- merge semantics


def test_merge_is_a_deep_merge_for_mappings() -> None:
    base = {"review": {"max_findings": 30, "min_severity_inline": "minor"}}
    merged = merge_layers(base, {"review": {"max_findings": 5}})
    assert merged["review"] == {"max_findings": 5, "min_severity_inline": "minor"}
    assert base["review"]["max_findings"] == 30


def test_lists_are_replaced_by_default() -> None:
    base = SquadFields().model_dump(mode="json")
    merged = merge_layers(base, {"trigger": {"events": ["comment"]}})
    assert merged["trigger"]["events"] == ["comment"]


def test_mergeable_sets_are_unioned_in_base_order() -> None:
    base = SquadFields().model_dump(mode="json")
    merged = merge_layers(
        base, {"implementer": {"protected_paths": ["infra/**", ".gitlab-ci.yml"]}}
    )
    paths = merged["implementer"]["protected_paths"]
    assert paths[0] == ".gitlab-ci.yml"
    assert paths.count(".gitlab-ci.yml") == 1
    assert "infra/**" in paths
    assert len(paths) == len(set(paths))


def test_mergeable_routes_can_only_grow() -> None:
    base = SquadFields().model_dump(mode="json")
    before = len(base["routing"]["routes"])
    merged = merge_layers(
        base,
        {
            "routing": {
                "routes": [{"glob": "src/hooks/**", "agents": ["jim"], "requires": []}]
            }
        },
    )
    assert len(merged["routing"]["routes"]) == before + 1
    assert merged["routing"]["routes"][:before] == base["routing"]["routes"]


def test_agent_entries_merge_per_agent() -> None:
    base = _base()
    merged = merge_layers(
        base,
        {"agents": {"dwight": {"model": "a"}}},
    )
    merged = merge_layers(merged, {"agents": {"jim": {"model": "b"}}})
    assert merged["agents"] == {"dwight": {"model": "a"}, "jim": {"model": "b"}}


def test_merge_does_not_mutate_its_inputs() -> None:
    base = SquadFields().model_dump(mode="json")
    overlay = {"review": {"max_findings": 3}}
    merge_layers(base, overlay)
    assert base["review"]["max_findings"] == 30
    assert overlay == {"review": {"max_findings": 3}}


# ---------- org_only


def test_repo_cannot_change_vcs_base_url() -> None:
    reasons = _reasons(_base(), {"vcs": {"base_url": "https://evil.example"}})
    assert any(r.startswith("vcs.base_url:") for r in reasons)


def test_restating_an_org_only_value_is_not_a_change() -> None:
    base = _base(vcs__base_url="https://gitlab.example.com")
    assert _reasons(base, {"vcs": {"base_url": "https://gitlab.example.com"}}) == []


def test_repo_cannot_add_an_egress_host() -> None:
    reasons = _reasons(
        _base(), {"security": {"allowed_hosts": ["api.osv.dev", "evil.example"]}}
    )
    assert any("security.allowed_hosts" in r for r in reasons)


def test_repo_cannot_enable_writes_when_org_forces_dry_run() -> None:
    base = _base(posting__force_dry_run=True)
    reasons = _reasons(base, {"posting": {"force_dry_run": False}})
    assert any("posting.force_dry_run" in r for r in reasons)


def test_repo_cannot_change_the_platform_limits() -> None:
    reasons = _reasons(_base(), {"limits": {"max_tokens": 900000}})
    assert any(r.startswith("limits") for r in reasons)


def test_repo_cannot_set_extra_agents_or_knowledge_dirs() -> None:
    extra = [{"id": "oscar", "description": "x", "prompt_path": "/p.md"}]
    assert any("extra_agents" in r for r in _reasons(_base(), {"extra_agents": extra}))
    dirs = {"agents": {"dwight": {"knowledge_extra_dirs": ["/etc"]}}}
    assert any("knowledge_extra_dirs" in r for r in _reasons(_base(), dirs))


def test_repo_cannot_read_skills_from_head() -> None:
    reasons = _reasons(_base(), {"skills": {"ref": "head"}})
    assert any("skills.ref" in r for r in reasons)


def test_repo_cannot_change_ops_or_observability_endpoints() -> None:
    assert _reasons(_base(), {"ops": {"prometheus_url": "https://p.example"}})
    assert _reasons(_base(), {"observability": {"content_capture": "FULL"}})
    assert _reasons(_base(), {"llm": {"base_url": "https://gw.example"}})


# ---------- tighten_only: tools, commenters, sources


def test_repo_cannot_add_a_tool_to_an_allowlist() -> None:
    base = _base(agents__dwight__tool_allowlist=["read_file", "finish"])
    reasons = _reasons(
        base,
        {"agents": {"dwight": {"tool_allowlist": ["read_file", "publish_review"]}}},
    )
    assert any("tool_allowlist" in r and "publish_review" in r for r in reasons)


def test_repo_may_narrow_a_tool_allowlist() -> None:
    base = _base(agents__dwight__tool_allowlist=["read_file", "finish"])
    assert _reasons(base, {"agents": {"dwight": {"tool_allowlist": ["finish"]}}}) == []


def test_allowed_commenters_can_only_shrink() -> None:
    base = _base(trigger__allowed_commenters=["alice", "bob"])
    assert _reasons(base, {"trigger": {"allowed_commenters": ["bob"]}}) == []
    assert any(
        "allowed_commenters" in r
        for r in _reasons(base, {"trigger": {"allowed_commenters": ["mallory"]}})
    )


def test_allowed_commenters_cannot_be_added_when_org_has_none() -> None:
    assert _reasons(_base(), {"trigger": {"allowed_commenters": ["alice"]}})


def test_skill_sources_can_only_narrow() -> None:
    assert _reasons(_base(), {"skills": {"allowed_sources": ["payload"]}}) == []
    assert _reasons(_base(), {"skills": {"allowed_sources": ["payload", "http"]}})


# ---------- tighten_only: booleans, enums, thresholds


def test_repo_cannot_loosen_approve_mode() -> None:
    reasons = _reasons(_base(), {"vcs": {"approve_mode": "approve"}})
    assert any("vcs.approve_mode" in r for r in reasons)


@pytest.mark.parametrize("value", ["none", "comment"])
def test_repo_may_tighten_approve_mode(value: str) -> None:
    base = _base(vcs__approve_mode="approve")
    assert _reasons(base, {"vcs": {"approve_mode": value}}) == []


def test_repo_cannot_turn_off_request_changes_on_blocker() -> None:
    reasons = _reasons(
        _base(), {"review": {"verdict": {"request_changes_on_blocker": False}}}
    )
    assert any("request_changes_on_blocker" in r for r in reasons)


def test_repo_cannot_enable_specialist_posting() -> None:
    assert _reasons(_base(), {"routing": {"specialists_post": True}})


def test_severity_thresholds_may_only_be_lowered() -> None:
    assert (
        _reasons(_base(), {"security": {"severity_mapping": {"cvss_blocker": 7.5}}})
        == []
    )
    raised = _reasons(
        _base(), {"security": {"severity_mapping": {"cvss_blocker": 9.5}}}
    )
    assert any("cvss_blocker" in r for r in raised)


def test_routing_size_thresholds_may_only_be_lowered() -> None:
    assert _reasons(_base(), {"routing": {"size_thresholds": {"high": 500}}}) == []
    assert _reasons(_base(), {"routing": {"size_thresholds": {"high": 5000}}})


def test_llm_budget_cap_cannot_be_raised_or_removed() -> None:
    capped = _base(llm__budget_usd_per_day=100.0)
    assert _reasons(capped, {"llm": {"budget_usd_per_day": 50.0}}) == []
    assert _reasons(capped, {"llm": {"budget_usd_per_day": 150.0}})
    assert _reasons(capped, {"llm": {"budget_usd_per_day": None}})


def test_llm_budget_cap_may_be_set_when_none_is_inherited() -> None:
    assert _reasons(_base(), {"llm": {"budget_usd_per_day": 75.0}}) == []


# ---------- tighten_only: ceilings


def test_budget_above_platform_limits_is_rejected() -> None:
    reasons = _reasons(_base(), {"agents": {"dwight": {"budgets": {"tokens": 250000}}}})
    assert any(
        "agents.dwight.budgets.tokens" in r and "limits.max_tokens" in r
        for r in reasons
    )


def test_budget_at_platform_limit_is_allowed() -> None:
    assert (
        _reasons(_base(), {"agents": {"dwight": {"budgets": {"tokens": 200000}}}}) == []
    )


@pytest.mark.parametrize(
    ("overlay", "ceiling"),
    [
        ({"budgets": {"wall_clock_seconds": 9999}}, "limits.max_wall_clock_seconds"),
        ({"budgets": {"tool_calls": 999}}, "limits.max_tool_calls"),
        ({"max_iterations": 99}, "limits.max_iterations"),
        ({"max_tokens": 999999}, "limits.max_tokens"),
    ],
)
def test_agent_numeric_budgets_respect_platform_ceilings(
    overlay: dict[str, Any], ceiling: str
) -> None:
    reasons = _reasons(_base(), {"agents": {"dwight": overlay}})
    assert any(ceiling in r for r in reasons)


def test_prompt_extra_longer_than_the_platform_limit_is_rejected() -> None:
    long_text = "x" * 4001
    reasons = _reasons(_base(), {"agents": {"jim": {"prompt_extra": long_text}}})
    assert any("limits.max_prompt_extra_chars" in r for r in reasons)


def test_skill_limits_cannot_exceed_platform_ceilings() -> None:
    reasons = _reasons(
        _base(), {"skills": {"max_skills": 80, "max_total_bytes": 300000}}
    )
    assert any("limits.max_skills" in r for r in reasons)
    assert any("limits.max_total_skill_bytes" in r for r in reasons)


def test_sandbox_timeout_cannot_exceed_platform_wall_clock() -> None:
    reasons = _reasons(_base(), {"implementer": {"sandbox": {"timeout_seconds": 7200}}})
    assert any("limits.max_wall_clock_seconds" in r for r in reasons)


# ---------- floor rules


def test_repo_cannot_disable_a_floor_rule() -> None:
    reasons = _reasons(
        _base(), {"agents": {"dwight": {"disabled_rules": ["SEC-INJ-001"]}}}
    )
    assert any("floor rule" in r and "SEC-INJ-001" in r for r in reasons)


def test_repo_cannot_downgrade_a_floor_rule() -> None:
    reasons = _reasons(
        _base(),
        {"agents": {"dwight": {"severity_overrides": {"sec-xss-001": "major"}}}},
    )
    assert any("cannot be downgraded" in r for r in reasons)


def test_repo_can_disable_a_non_floor_rule_and_raise_a_floor_rule() -> None:
    overlay = {
        "agents": {
            "dwight": {
                "disabled_rules": ["DWIGHT-STYLE-010"],
                "severity_overrides": {
                    "SEC-INJ-001": "blocker",
                    "DWIGHT-STYLE-010": "nit",
                },
            }
        }
    }
    assert _reasons(_base(), overlay) == []


# ---------- secret references


def test_secret_reference_outside_allowed_patterns_is_rejected() -> None:
    reasons = _reasons(_base(), {"llm": {"api_key_secret": "Prod.Token"}})
    assert any("outside secrets.allowed_patterns" in r for r in reasons)


def test_secret_reference_inside_allowed_patterns_is_accepted() -> None:
    assert _reasons(_base(), {"llm": {"api_key_secret": "llm-key"}}) == []


def test_secret_check_uses_the_org_patterns() -> None:
    base = _base(secrets__allowed_patterns=["^team-[a-z]+$"])
    assert _reasons(base, {"llm": {"api_key_secret": "llm-key"}})
    assert _reasons(base, {"llm": {"api_key_secret": "team-llm"}}) == []


# ---------- layers and messages


def test_the_same_rules_apply_to_call_overrides() -> None:
    reasons = _reasons(
        _base(), {"vcs": {"base_url": "https://x.example"}}, layer="call"
    )
    assert any("call layer" in r for r in reasons)
    loosened = _reasons(_base(), {"vcs": {"approve_mode": "approve"}}, layer="call")
    assert any("the call layer may not loosen" in r for r in loosened)


def test_floor_severity_override_to_blocker_is_fine() -> None:
    assert (
        _reasons(
            _base(),
            {
                "agents": {
                    "dwight": {"severity_overrides": {"SEC-DESER-001": "blocker"}}
                }
            },
        )
        == []
    )


def test_no_violations_for_a_plain_tightening_overlay() -> None:
    overlay = {
        "review": {"min_confidence_to_publish": "low", "max_findings": 10},
        "trigger": {"skip_draft": True},
        "implementer": {"protected_paths": [".github/**"]},
    }
    assert _reasons(_base(), overlay) == []


# ---------- routing.always_run cannot be disabled by a lower layer


@pytest.mark.parametrize("layer", ["repo", "call"])
def test_lower_layers_cannot_disable_an_always_run_agent(layer: Layer) -> None:
    reasons = _reasons(_base(), {"agents": {"dwight": {"enabled": False}}}, layer=layer)
    assert reasons == [
        f"agents.dwight.enabled: agent 'dwight' is in routing.always_run and "
        f"cannot be disabled at the {layer} layer"
    ]


@pytest.mark.parametrize("value", ["false", "no", 0])
def test_string_or_integer_forms_of_disabling_are_caught(value: Any) -> None:
    overlay = {"agents": {"dwight": {"enabled": value}}}
    assert _reasons(_base(), overlay)


def test_always_run_is_read_from_the_base_effective_config() -> None:
    base = _base(routing__always_run=["dwight", "jim"])
    assert _reasons(base, {"agents": {"jim": {"enabled": False}}})
    assert _reasons(base, {"agents": {"jim": {"enabled": False}}}, layer="call")


@pytest.mark.parametrize("layer", ["repo", "call"])
def test_disabling_an_agent_outside_always_run_is_allowed(layer: Layer) -> None:
    assert _reasons(_base(), {"agents": {"jim": {"enabled": False}}}, layer=layer) == []


def test_restating_an_always_run_agent_as_enabled_is_allowed() -> None:
    assert _reasons(_base(), {"agents": {"dwight": {"enabled": True}}}) == []
