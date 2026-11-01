from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from code_squad._common.config import schema as schema_module
from code_squad._common.config.meta import merge_policy
from code_squad._common.config.schema import (
    AcceptedRisk,
    AgentConfig,
    Budgets,
    ProjectsFile,
    RepoConfig,
    ReviewConfig,
    SecretsConfig,
    SquadConfig,
    SquadFields,
    VcsAuth,
    VcsConfig,
)

ROOT = Path(__file__).resolve().parents[2]


def _walk_models(
    model: type[BaseModel], seen: set[type[BaseModel]]
) -> list[type[BaseModel]]:
    if model in seen:
        return []
    seen.add(model)
    found = [model]
    for info in model.model_fields.values():
        annotation: Any = info.annotation
        candidates = [annotation, *getattr(annotation, "__args__", ())]
        for candidate in candidates:
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                found.extend(_walk_models(candidate, seen))
    return found


def test_defaults_build_a_valid_config() -> None:
    config = SquadConfig()
    dumped = config.model_dump(mode="json")
    assert set(dumped) == set(SquadFields.model_fields)
    assert dumped["vcs"]["provider"] == "auto"
    assert dumped["vcs"]["approve_mode"] == "none"
    assert dumped["review"]["max_findings"] == 30


# Fields that are mandatory by design (identity, or a mandatory expiry or reason).
MANDATORY_FIELDS = {
    "Route.glob",
    "Route.agents",
    "ExtraAgent.id",
    "ExtraAgent.description",
    "ExtraAgent.prompt_path",
    "AcceptedRisk.id",
    "AcceptedRisk.reason",
    "AcceptedRisk.expires",
    "ProjectEntry.match",
}


def test_every_field_has_a_description_and_all_but_the_mandatory_have_defaults() -> (
    None
):
    problems: list[str] = []
    required: set[str] = set()
    seen: set[type[BaseModel]] = set()
    roots: list[type[BaseModel]] = [RepoConfig, ProjectsFile]
    models = [model for root in roots for model in _walk_models(root, seen)]
    for model in models:
        for name, info in model.model_fields.items():
            label = f"{model.__name__}.{name}"
            if not info.description:
                problems.append(f"{label}: no description")
            if info.is_required():
                required.add(label)
    assert problems == []
    assert required == MANDATORY_FIELDS


def test_unknown_keys_are_rejected_everywhere() -> None:
    with pytest.raises(ValidationError):
        SquadFields.model_validate({"vcs": {"provder": "github"}})
    with pytest.raises(ValidationError):
        SquadFields.model_validate({"agents": {"dwight": {"modle": "x"}}})


def test_extends_is_only_allowed_in_repo_files() -> None:
    with pytest.raises(ValidationError):
        SquadFields.model_validate({"extends": "strict"})
    assert RepoConfig.model_validate({"extends": "strict"}).extends == "strict"


def test_merge_policy_helper_reports_declared_policies() -> None:
    assert merge_policy(VcsConfig, "bot_username") == "free"
    assert merge_policy(VcsConfig, "approve_mode") == "tighten_only"
    assert merge_policy(VcsConfig, "provider") == "org_only"
    assert merge_policy(VcsConfig, "auth") == "org_only"
    assert merge_policy(VcsConfig, "base_url") == "org_only"
    assert merge_policy(SquadFields, "limits") == "org_only"
    assert merge_policy(Budgets, "tool_calls") == "tighten_only"


def test_json_schema_carries_merge_policy_metadata(tmp_path: Path) -> None:
    schema = json.loads((ROOT / "schemas" / "squad-config.schema.json").read_text())
    vcs = schema["$defs"]["VcsConfig"]["properties"]
    assert vcs["base_url"]["x-merge"] == "org_only"
    assert vcs["approve_mode"]["x-merge"] == "tighten_only"
    assert vcs["approve_mode"]["x-order"] == ["none", "comment", "approve"]


@pytest.mark.parametrize("agent_id", ["jim", "michael", "pam"])
def test_extra_agent_cannot_reuse_a_builtin_id(agent_id: str) -> None:
    extra = {"id": agent_id, "description": "x", "prompt_path": "/p.md"}
    with pytest.raises(ValidationError, match="collides with a built-in"):
        SquadFields.model_validate({"extra_agents": [extra]})


@pytest.mark.parametrize("agent_id", ["Oscar", "oscar-py", "1oscar", "o"])
def test_extra_agent_id_must_be_a_lowercase_token(agent_id: str) -> None:
    extra = {"id": agent_id, "description": "x", "prompt_path": "/p.md"}
    with pytest.raises(ValidationError):
        SquadFields.model_validate({"extra_agents": [extra]})


def test_duplicate_extra_agent_ids_are_rejected() -> None:
    extra = {"id": "oscar", "description": "x", "prompt_path": "/p.md"}
    with pytest.raises(ValidationError, match="duplicate extra agent"):
        SquadFields.model_validate({"extra_agents": [extra, extra]})


def test_effective_config_rejects_budgets_above_platform_limits() -> None:
    raw = {"agents": {"dwight": {"budgets": {"wall_clock_seconds": 9999}}}}
    with pytest.raises(
        ValidationError, match=r"platform ceiling limits\.max_wall_clock"
    ):
        SquadConfig.model_validate(raw)


def test_effective_config_accepts_budgets_within_limits() -> None:
    raw = {"agents": {"dwight": {"budgets": {"wall_clock_seconds": 1200}}}}
    assert (
        SquadConfig.model_validate(raw).agents["dwight"].budgets.wall_clock_seconds
        == 1200
    )


def test_secret_names_must_match_the_name_shape() -> None:
    with pytest.raises(ValidationError):
        VcsAuth.model_validate({"token_secret": "Bad Name/with-slash"})
    assert VcsAuth.model_validate({"token_secret": "gitlab-token"}).token_secret


def test_secret_patterns_must_compile() -> None:
    with pytest.raises(ValidationError, match="invalid secret pattern"):
        SecretsConfig.model_validate({"allowed_patterns": ["["]})


def test_accepted_risk_requires_a_reason_and_expiry() -> None:
    with pytest.raises(ValidationError):
        AcceptedRisk.model_validate({"id": "CVE-2024-1", "reason": "x"})
    risk = AcceptedRisk.model_validate(
        {"id": "CVE-2024-1", "reason": "x", "expires": "2027-01-01"}
    )
    assert risk.expires == date(2027, 1, 1)


def test_schema_defaults_match_the_brief() -> None:
    config = SquadConfig()
    assert config.skills.max_skills == 20
    assert config.skills.max_skill_bytes == 20480
    assert config.skills.max_total_bytes == 81920
    assert config.routing.always_run == ["dwight"]
    assert config.routing.size_thresholds.medium == 300
    assert config.routing.size_thresholds.high == 1000
    assert config.security.severity_mapping.cvss_blocker == 9.0
    assert config.security.cache_ttl_seconds == 21600
    assert config.implementer.branch_template == "pam/{task_key}-{slug}"
    assert config.implementer.mr_draft is False
    assert config.implementer.sandbox.timeout_seconds == 1800
    assert config.limits.max_tokens == 200000
    assert config.secrets.provider == "k8s_files"
    assert config.posting.force_dry_run is False
    assert config.trigger.debounce_seconds == 30
    assert config.trigger.skip_labels == ["skip-squad"]
    assert config.review.min_confidence_to_publish == "medium"
    assert config.routing.timeouts_seconds == {"default": 600}


def test_default_agent_budgets_fit_within_platform_limits() -> None:
    budgets = Budgets()
    limits = SquadConfig().limits
    assert budgets.wall_clock_seconds <= limits.max_wall_clock_seconds


def test_repo_config_model_accepts_partial_documents() -> None:
    parsed: dict[str, Any] = RepoConfig.model_validate(
        {"review": {"max_findings": 5}}
    ).model_dump(exclude_unset=True)
    assert parsed == {"review": {"max_findings": 5}}


def test_b2_new_fields_have_their_documented_defaults() -> None:
    config = SquadConfig()
    assert config.llm.allowed_models == []
    assert config.limits.max_request_bytes == 1_000_000
    assert config.limits.max_run_tokens == 400_000
    assert config.implementer.allowed_protected_paths == []
    assert config.trigger.allowed_assigners == []
    assert config.trigger.skip_bot_authors is False


@pytest.mark.parametrize(
    "raw",
    [
        {"agents": {"dwight": {"disabled_rules": []}}},
        {"agents": {"dwight": {"severity_overrides": {}}}},
        {"agents": {"dwight": {"language": "en"}}},
        {"agents": {"dwight": {"budgets": {"tokens": 1000}}}},
        {"agents": {"dwight": {"budgets": {"cost_hint_usd": 1.0}}}},
        {"review": {"summary_template": None}},
        {"review": {"chunking": "truncate"}},
        {"review": {"suppressions_enabled": True}},
        {"review": {"baseline_file": ".squad/baseline.yml"}},
        {"review": {"verdict": {"request_changes_on_blocker": True}}},
        {"trigger": {"slash_commands": ["review"]}},
        {"vcs": {"status_mode": "auto"}},
        {"llm": {"tag_template": ["squad:code-squad"]}},
        {"llm": {"aliases": {}}},
        {"llm": {"budget_usd_per_day": 5}},
        {"llm": {"api_key_secret": "llm-api-key"}},
        {"observability": {"sampling_ratio": 1.0}},
        {"observability": {"content_capture": "METADATA"}},
        {"observability": {"log_level": "INFO"}},
        {"observability": {"otlp_endpoint": None}},
        {"ops": {"incident_window_minutes": 60}},
        {"implementer": {"sandbox": {"image": "img:latest"}}},
        {"implementer": {"sandbox": {"cpu": "1"}}},
        {"implementer": {"sandbox": {"memory": "1Gi"}}},
        {"security": {"local_scanners": {"gitleaks": True}}},
        {"limits": {"max_tool_calls": 10}},
    ],
)
def test_keys_without_run_time_effect_are_not_in_the_schema(
    raw: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        SquadFields.model_validate(raw)


def test_enforced_keys_that_remain_in_the_schema() -> None:
    agent = AgentConfig.model_validate(
        {"fallback_model": "haiku-5-5", "budgets": {"tool_calls": 40}}
    )
    assert agent.fallback_model == "haiku-5-5"
    assert agent.budgets.tool_calls == 40
    assert agent.budgets.wall_clock_seconds == 900
    assert ReviewConfig().max_diff_bytes == 400000


def test_baseline_model_and_module_are_gone() -> None:
    import importlib.util

    assert importlib.util.find_spec("code_squad._common.config.baseline") is None
    assert importlib.util.find_spec("code_squad._common.config.reload") is None
    assert not hasattr(schema_module, "Baseline")


def test_accepted_risk_scope_fields_are_optional() -> None:
    risk = AcceptedRisk.model_validate(
        {
            "id": "CVE-2024-1",
            "reason": "x",
            "expires": "2027-01-01",
            "package": "lodash",
            "path": "services/web/**",
        }
    )
    assert (risk.package, risk.path) == ("lodash", "services/web/**")
