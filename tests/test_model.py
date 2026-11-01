from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from strands.models.openai import OpenAIModel

from code_squad._common import model as model_module
from code_squad._common.model import (
    build_model,
    get_model_factory,
    litellm_tags,
    set_model_factory,
)
from tests.support import FAKE_TOKEN


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ("LLM_API_KEY", "LLM_API_KEY_FILE", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    yield
    set_model_factory(None)


def test_build_model_uses_gateway_settings_and_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", FAKE_TOKEN)
    monkeypatch.setenv("LLM_BASE_URL", "http://litellm.test/v1")
    model = build_model("sonnet-5-5", 512, 0.2, ["squad:code-squad", "agent:jim"])
    assert isinstance(model, OpenAIModel)
    config = model.get_config()
    assert config["model_id"] == "sonnet-5-5"
    assert config["params"] == {
        "max_tokens": 512,
        "temperature": 0.2,
        "extra_body": {"metadata": {"tags": ["squad:code-squad", "agent:jim"]}},
    }
    assert model.client_args == {
        "base_url": "http://litellm.test/v1",
        "api_key": FAKE_TOKEN,
    }


def test_build_model_without_tags_sends_no_extra_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", FAKE_TOKEN)
    config = build_model("haiku-5-5", 64, 0.0).get_config()
    assert "extra_body" not in (config["params"] or {})


def test_api_key_can_come_from_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key_file = tmp_path / "llm-key"
    key_file.write_text(f"{FAKE_TOKEN}\n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(key_file))
    model = build_model("sonnet-5-5", 64, 0.0)
    assert isinstance(model, OpenAIModel)
    assert model.client_args["api_key"] == FAKE_TOKEN


def test_missing_api_key_fails_before_any_call() -> None:
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        build_model("sonnet-5-5", 64, 0.0)


def test_factory_override_is_used_until_reset() -> None:
    sentinel = object()

    def _override(*_args: object) -> object:
        return sentinel

    set_model_factory(_override)  # type: ignore[arg-type]
    assert get_model_factory() is _override
    set_model_factory(None)
    assert get_model_factory() is model_module.build_model


def test_litellm_tags_order_and_optional_project() -> None:
    assert litellm_tags("jim", "group/repo", ["team:web"]) == [
        "squad:code-squad",
        "agent:jim",
        "project:group/repo",
        "team:web",
    ]
    assert litellm_tags("dwight", None, []) == ["squad:code-squad", "agent:dwight"]


def test_caller_tags_in_reserved_namespaces_are_dropped() -> None:
    from code_squad._common.model import dropped_caller_tags

    extra = ["squad:forged", "project:other", "agent:angela", "team:web"]
    assert litellm_tags("jim", "group/repo", extra) == [
        "squad:code-squad",
        "agent:jim",
        "project:group/repo",
        "team:web",
    ]
    assert dropped_caller_tags(extra) == ["squad", "project", "agent"]
