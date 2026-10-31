from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from pydantic import ValidationError

from code_squad._common.contract import InvocationRequest
from code_squad._common.spec import AgentSpec

AGENT_INPUT_KEYS: Final = frozenset({"symptom", "task", "question", "change_request"})


class ValidationFailure(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def validate_invocation(raw: Mapping[str, Any], spec: AgentSpec) -> InvocationRequest:
    if not isinstance(raw, dict):
        raise ValidationFailure(["body must be a JSON object"])
    errors = _foreign_key_errors(raw, spec)
    try:
        request = InvocationRequest.model_validate(raw)
    except ValidationError as exc:
        errors.extend(_pydantic_errors(exc))
        raise ValidationFailure(errors) from None
    errors.extend(_policy_errors(request, spec))
    if errors:
        raise ValidationFailure(errors)
    return request


def _foreign_key_errors(raw: Mapping[str, Any], spec: AgentSpec) -> list[str]:
    foreign = AGENT_INPUT_KEYS - {spec.input_key}
    return [
        f"input key '{key}' belongs to another agent"
        for key in sorted(raw)
        if key in foreign
    ]


def _pydantic_errors(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in err['loc']) or 'body'}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False)
    ]


def _policy_errors(request: InvocationRequest, spec: AgentSpec) -> list[str]:
    errors: list[str] = []
    if request.mode is not None and request.mode.value not in spec.modes:
        errors.append(
            f"mode '{request.mode.value}' is not supported by agent '{spec.name}'"
        )
    if request.attachments and not spec.accepts_attachments:
        errors.append(f"agent '{spec.name}' does not accept attachments")
    return errors
