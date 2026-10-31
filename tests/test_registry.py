from __future__ import annotations

import pytest

from code_squad._common.registry import (
    AGENT_IDS,
    ROLES,
    UnknownAgentError,
    all_specs,
    get_spec,
)


def test_all_six_agents_load_with_matching_names_and_roles() -> None:
    assert AGENT_IDS == ("michael", "jim", "angela", "dwight", "darryl", "pam")
    specs = all_specs()
    assert [spec.name for spec in specs] == list(AGENT_IDS)
    for spec in specs:
        assert spec.role == ROLES[spec.name]
        assert spec.description
        assert spec.system_prompt.startswith("# ")


def test_unknown_agent_is_rejected() -> None:
    with pytest.raises(UnknownAgentError):
        get_spec("toby")


def test_env_overrides_are_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_ID", "custom-model")
    monkeypatch.setenv("AGENT_MAX_TOKENS", "1024")
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "4")
    monkeypatch.setenv("AGENT_TEMPERATURE", "0.5")
    spec = get_spec("jim")
    assert spec.model_id == "custom-model"
    assert spec.max_tokens == 1024
    assert spec.max_iterations == 4
    assert spec.temperature == 0.5


def test_defaults_are_used_without_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AGENT_MODEL_ID",
        "AGENT_MAX_TOKENS",
        "AGENT_MAX_ITERATIONS",
        "AGENT_TEMPERATURE",
    ):
        monkeypatch.delenv(name, raising=False)
    assert get_spec("michael").model_id == "haiku-5-5"
    assert get_spec("jim").model_id == "sonnet-5-5"
    assert get_spec("jim").max_iterations == 25


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AGENT_MAX_TOKENS", "abc"),
        ("AGENT_MAX_TOKENS", "0"),
        ("AGENT_MAX_ITERATIONS", "-1"),
        ("AGENT_MAX_ITERATIONS", "2.5"),
        ("AGENT_TEMPERATURE", "hot"),
        ("AGENT_TEMPERATURE", "3"),
    ],
)
def test_invalid_env_overrides_raise(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        get_spec("darryl")
