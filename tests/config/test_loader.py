from __future__ import annotations

from pathlib import Path

import pytest

from code_squad._common.config.errors import ConfigError
from code_squad._common.config.loader import (
    ConfigSources,
    apply_env_overrides,
    load_org,
)
from tests.config.support import write


def _sources(tmp: Path, text: str | None, env: dict[str, str]) -> ConfigSources:
    path = write(tmp, "squad.yaml", text) if text is not None else None
    return ConfigSources(path, env, None, None)


def test_nested_env_variables_set_nested_keys(tmp_path: Path) -> None:
    org = load_org(
        _sources(tmp_path, None, {"SQUAD__AGENTS__DWIGHT__MODEL": "sonnet-5-5"})
    )
    assert org == {"agents": {"dwight": {"model": "sonnet-5-5"}}}


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("SQUAD__REVIEW__MAX_FINDINGS", "12", 12),
        ("SQUAD__TRIGGER__ON_PUSH", "true", True),
        (
            "SQUAD__TRIGGER__EVENTS",
            "[comment, issue_assigned]",
            ["comment", "issue_assigned"],
        ),
        ("SQUAD__VCS__AUTH__APP_ID", "42", 42),
        ("SQUAD__LLM__BUDGET_USD_PER_DAY", "12.5", 12.5),
        ("SQUAD__OBSERVABILITY__LOG_LEVEL", "DEBUG", "DEBUG"),
    ],
)
def test_env_values_are_parsed_as_yaml_scalars(
    name: str, value: str, expected: object
) -> None:
    raw = apply_env_overrides({}, {name: value})
    node: object = raw
    for part in name.removeprefix("SQUAD__").lower().split("__"):
        assert isinstance(node, dict)
        node = node[part]
    assert node == expected


def test_env_overrides_the_org_file(tmp_path: Path) -> None:
    org = load_org(
        _sources(
            tmp_path,
            "agents:\n  dwight:\n    model: haiku-5-5\n    language: fr\n",
            {"SQUAD__AGENTS__DWIGHT__MODEL": "sonnet-5-5"},
        )
    )
    assert org["agents"]["dwight"] == {"model": "sonnet-5-5", "language": "fr"}


def test_only_squad_prefixed_variables_are_read(tmp_path: Path) -> None:
    org = load_org(_sources(tmp_path, None, {"AGENT_MODEL_ID": "x", "PATH": "/bin"}))
    assert org == {}


def test_empty_path_segment_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="empty path segment"):
        load_org(_sources(tmp_path, None, {"SQUAD____X": "1"}))


def test_setting_a_child_of_a_scalar_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="non-mapping"):
        load_org(
            _sources(
                tmp_path,
                None,
                {"SQUAD__REVIEW": "x", "SQUAD__REVIEW__MAX_FINDINGS": "3"},
            )
        )


def test_invalid_env_value_fails_validation(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"review\.max_findings"):
        load_org(_sources(tmp_path, None, {"SQUAD__REVIEW__MAX_FINDINGS": "lots"}))


def test_missing_org_file_means_defaults(tmp_path: Path) -> None:
    org = load_org(ConfigSources(tmp_path / "absent.yaml", {}, None, None))
    assert org == {}


def test_org_file_must_be_a_mapping(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_org(_sources(tmp_path, "- a\n- b\n", {}))


def test_invalid_org_yaml_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"org config .* is not valid YAML"):
        load_org(_sources(tmp_path, "review: [oops\n", {}))


def test_org_file_with_unknown_key_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="org config is invalid"):
        load_org(_sources(tmp_path, "reveiw:\n  max_findings: 3\n", {}))


def test_org_file_cross_checks_platform_ceilings(tmp_path: Path) -> None:
    text = (
        "limits:\n  max_tokens: 1000\n"
        "agents:\n  dwight:\n    budgets:\n      tokens: 5000\n"
    )
    with pytest.raises(ConfigError, match="platform ceiling"):
        load_org(_sources(tmp_path, text, {}))
