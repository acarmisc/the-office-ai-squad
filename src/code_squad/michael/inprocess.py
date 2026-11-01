"""Specialists run in this process, for michael in a CI job.

``InProcessSpecialistClient`` satisfies the ``SpecialistClient`` protocol that michael's
fan-out uses for HTTP. Each call goes through ``execute_invocation`` with the same
services factory, and the specialist never publishes: ``post`` is forced to false, so
michael alone writes the summary and the status. The fan-out runs calls in threads and
enforces the timeout; a specialist that overruns keeps running until it returns, because
a thread cannot be stopped.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from code_squad._common.contract import InvocationResult
from code_squad._common.execute import (
    InvocationRefused,
    ServicesFactory,
    execute_invocation,
)
from code_squad._common.model import ModelFactory
from code_squad._common.validation import ValidationFailure
from code_squad.michael.fanout import SpecialistError


class InProcessSpecialistClient:
    def __init__(
        self,
        services_factory: ServicesFactory,
        model_factory: ModelFactory | None = None,
    ) -> None:
        self._services = services_factory
        self._models = model_factory

    def bind(self, configured: Mapping[str, str]) -> InProcessSpecialistClient:
        return self

    def invoke(
        self,
        agent: str,
        payload: dict[str, Any],
        *,
        timeout_s: float,
        idempotency_key: str,
        trace_headers: Mapping[str, str],
    ) -> InvocationResult:
        body: dict[str, Any] = {
            key: value for key, value in payload.items() if key != "idempotency_key"
        }
        body["post"] = False
        try:
            return execute_invocation(
                agent,
                body,
                services_factory=self._services,
                model_factory=self._models,
            )
        except (ValidationFailure, InvocationRefused) as exc:
            raise SpecialistError(f"request for {agent} was refused") from exc
