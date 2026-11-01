from __future__ import annotations

import dataclasses
import hashlib
from typing import Any, cast

import pytest

from code_squad._common.contract import InvocationRequest
from code_squad._common.registry import get_spec
from code_squad._common.spec import AgentSpec
from code_squad._common.validation import ValidationFailure, validate_invocation


@pytest.fixture
def michael() -> AgentSpec:
    return get_spec("michael")


@pytest.fixture
def jim() -> AgentSpec:
    return get_spec("jim")


def _errors(raw: Any, spec: AgentSpec) -> list[str]:
    with pytest.raises(ValidationFailure) as info:
        validate_invocation(raw, spec)
    return info.value.errors


def test_valid_request_is_returned_as_model(michael: AgentSpec) -> None:
    request = validate_invocation({"prompt": "review it", "post": True}, michael)
    assert isinstance(request, InvocationRequest)
    assert request.prompt == "review it"
    assert request.post is True


def test_non_object_body_is_rejected(michael: AgentSpec) -> None:
    assert _errors(cast(Any, ["prompt"]), michael) == ["body must be a JSON object"]
    assert _errors(cast(Any, "prompt"), michael) == ["body must be a JSON object"]


def test_unknown_key_is_rejected(michael: AgentSpec) -> None:
    errors = _errors({"prompt": "x", "bogus": 1}, michael)
    assert any("bogus" in error for error in errors)


@pytest.mark.parametrize("value", ["false", 0, 1, None, "no"])
def test_post_must_be_a_real_boolean(michael: AgentSpec, value: Any) -> None:
    errors = _errors({"prompt": "x", "post": value}, michael)
    assert any(error.startswith("post") for error in errors)


def test_post_error_does_not_echo_the_submitted_value(michael: AgentSpec) -> None:
    errors = _errors({"prompt": "x", "post": "SUPER-SECRET-VALUE"}, michael)
    assert all("SUPER-SECRET-VALUE" not in error for error in errors)


@pytest.mark.parametrize("key", ["symptom", "task", "question", "change_request"])
def test_foreign_input_key_is_rejected_with_specific_message(
    michael: AgentSpec, key: str
) -> None:
    errors = _errors({"prompt": "x", key: "value"}, michael)
    assert f"input key '{key}' belongs to another agent" in errors


def test_mode_not_supported_by_agent_is_rejected(jim: AgentSpec) -> None:
    errors = _errors({"prompt": "x", "mode": "advisor"}, jim)
    assert "mode 'advisor' is not supported by agent 'jim'" in errors


def test_mode_supported_by_agent_is_accepted(michael: AgentSpec) -> None:
    request = validate_invocation({"prompt": "x", "mode": "troubleshoot"}, michael)
    assert request.mode is not None
    assert request.mode.value == "troubleshoot"


def test_unknown_mode_value_is_rejected(michael: AgentSpec) -> None:
    errors = _errors({"prompt": "x", "mode": "destroy"}, michael)
    assert any(error.startswith("mode") for error in errors)


def _attachment(data: str = "hello") -> dict[str, Any]:
    return {
        "type": "text",
        "name": "log.txt",
        "media_type": "text/plain",
        "data": data,
        "sha256": hashlib.sha256(data.encode("utf-8")).hexdigest(),
    }


def test_attachments_are_refused_when_agent_does_not_accept_them(
    michael: AgentSpec,
) -> None:
    assert michael.accepts_attachments is False
    errors = _errors({"prompt": "x", "attachments": [_attachment()]}, michael)
    assert "agent 'michael' does not accept attachments" in errors


def test_attachments_are_accepted_when_agent_accepts_them(michael: AgentSpec) -> None:
    spec = dataclasses.replace(michael, accepts_attachments=True)
    request = validate_invocation({"prompt": "x", "attachments": [_attachment()]}, spec)
    assert len(request.attachments) == 1


def test_bad_attachment_digest_is_rejected_even_when_accepted(
    michael: AgentSpec,
) -> None:
    spec = dataclasses.replace(michael, accepts_attachments=True)
    bad = _attachment()
    bad["sha256"] = "0" * 64
    errors = _errors({"prompt": "x", "attachments": [bad]}, spec)
    assert any("sha256" in error for error in errors)


def test_all_problems_are_reported_together(michael: AgentSpec) -> None:
    errors = _errors({"prompt": "x", "symptom": "y", "post": "false"}, michael)
    assert "input key 'symptom' belongs to another agent" in errors
    assert any(error.startswith("post") for error in errors)


def test_missing_prompt_is_rejected(michael: AgentSpec) -> None:
    errors = _errors({"project": "group/repo"}, michael)
    assert any(error.startswith("prompt") for error in errors)
