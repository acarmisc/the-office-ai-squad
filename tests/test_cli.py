from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from code_squad._common.cli import app
from code_squad._common.fake_model import ScriptedModel
from code_squad._common.model import set_model_factory
from tests.support import finish_turn


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def scripted() -> Iterator[ScriptedModel]:
    model = ScriptedModel([finish_turn("approve", "CLI ok.")])
    set_model_factory(lambda *_args: model)
    yield model
    set_model_factory(None)


def test_invoke_prints_result_json(runner: CliRunner, scripted: ScriptedModel) -> None:
    result = runner.invoke(app, ["invoke", "michael", "hello", "--no-post"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "complete"
    assert payload["summary"] == "CLI ok."


def test_invoke_accepts_post_flag(runner: CliRunner, scripted: ScriptedModel) -> None:
    result = runner.invoke(app, ["invoke", "michael", "hello", "--post"])
    assert result.exit_code == 0, result.output
    assert "External writes are enabled" in (scripted.calls[0].system_prompt or "")


def test_invoke_rejects_unknown_agent(runner: CliRunner) -> None:
    result = runner.invoke(app, ["invoke", "toby", "hello"])
    assert result.exit_code == 2


def test_invoke_rejects_unsupported_mode(runner: CliRunner) -> None:
    result = runner.invoke(app, ["invoke", "jim", "hello", "--mode", "advisor"])
    assert result.exit_code == 2


def test_config_group_lists_its_commands(runner: CliRunner) -> None:
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    for command in ("schema", "validate", "explain", "init"):
        assert command in result.output
