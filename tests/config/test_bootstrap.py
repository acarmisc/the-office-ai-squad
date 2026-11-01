from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from code_squad._common.config.bootstrap import (
    BOOTSTRAP_ENV,
    NESTING_NOTE,
    render_env_example,
    render_env_table,
    single_project_entry,
)
from code_squad._common.secrets.base import VCS_TOKEN_SECRET


def _names() -> set[str]:
    return {var.name for var in BOOTSTRAP_ENV}


def test_bootstrap_table_covers_the_documented_variables() -> None:
    expected = {
        "AGENT_NAME",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_API_KEY_FILE",
        "VCS_PROVIDER",
        "VCS_BASE_URL",
        "VCS_TOKEN",
        "VCS_TOKEN_FILE",
        "SECRETS_DIR",
        "SQUAD_CONFIG_FILE",
        "SQUAD_PROJECTS_DIR",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "SESSION_STORE_URL",
        "ORCHESTRATOR_SPECIALIST_URLS",
        "EGRESS_PROXY_URL",
        "AGENT_MODEL_ID",
        "AGENT_MAX_TOKENS",
        "AGENT_MAX_ITERATIONS",
        "AGENT_TEMPERATURE",
        "AGENT_PROMPT_FILE",
    }
    assert expected <= _names()


def test_names_are_unique_and_defaults_match_the_brief() -> None:
    assert len(_names()) == len(BOOTSTRAP_ENV)
    defaults = {var.name: var.default for var in BOOTSTRAP_ENV}
    assert defaults["SECRETS_DIR"] == "/var/run/secrets/squad"
    assert defaults["SQUAD_CONFIG_FILE"] == "/etc/squad/squad.yaml"
    assert defaults["SQUAD_PROJECTS_DIR"] == "/etc/squad/projects"


def test_required_variables_are_marked() -> None:
    required = {var.name for var in BOOTSTRAP_ENV if var.required}
    assert required == {"AGENT_NAME", "LLM_BASE_URL"}


def test_rendered_table_lists_every_variable() -> None:
    table = render_env_table()
    for name in _names():
        assert f"`{name}`" in table


def test_rendered_example_has_one_assignment_per_variable() -> None:
    lines = [
        line
        for line in render_env_example().splitlines()
        if re.match(r"^[A-Z_]+=", line)
    ]
    assert len(lines) == len(BOOTSTRAP_ENV)
    assert "SECRETS_DIR=/var/run/secrets/squad" in lines


def test_nesting_note_documents_the_double_underscore_convention() -> None:
    assert "SQUAD__SECTION__KEY" in NESTING_NOTE
    assert "SQUAD__AGENTS__DWIGHT__MODEL" in NESTING_NOTE


def test_single_project_entry_needs_provider_and_base_url() -> None:
    assert single_project_entry({}, "acme/web") is None
    assert single_project_entry({"VCS_PROVIDER": "github"}, "acme/web") is None
    assert single_project_entry({"VCS_BASE_URL": "https://x"}, "acme/web") is None


def test_single_project_entry_uses_the_vcs_token_secret() -> None:
    entry = single_project_entry(
        {"VCS_PROVIDER": "gitlab", "VCS_BASE_URL": "https://gitlab.example.com"},
        "group/app",
    )
    assert entry is not None
    assert entry.match == "group/app"
    assert entry.provider == "gitlab"
    assert entry.auth is not None
    assert entry.auth.token_secret == VCS_TOKEN_SECRET


def test_single_project_entry_rejects_an_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        single_project_entry(
            {"VCS_PROVIDER": "bitbucket", "VCS_BASE_URL": "https://x"}, "a/b"
        )
