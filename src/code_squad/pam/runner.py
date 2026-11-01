from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Final

from code_squad._common.contract import (
    InvocationRequest,
    InvocationResult,
    Mode,
    RunStatus,
    Verdict,
)
from code_squad._common.model import ModelFactory
from code_squad._common.runtime import run_task
from code_squad._common.spec import AgentSpec
from code_squad.pam.session import CLEANUP_KEY, REPORT_KEY

_logger = logging.getLogger("code_squad.pam")
FACT_KEYS: Final = (
    "mode",
    "branch",
    "mr_url",
    "checks",
    "files_changed",
    "protected_paths_touched",
)


def run_pam(
    spec: AgentSpec,
    request: InvocationRequest,
    *,
    services: dict[str, Any] | None = None,
    model_factory: ModelFactory | None = None,
    post_override: bool | None = None,
) -> InvocationResult:
    """Run pam through the runtime and always destroy the sandbox afterwards.

    Implementer tools register their cleanup in ``services["cleanup"]``; this function
    runs every callback in a ``finally`` so a sandbox never outlives the invocation.
    """
    cleanups: list[Callable[[], None]] = []
    report = _initial_report(request)
    scoped: dict[str, Any] = {
        **dict(services or {}),
        CLEANUP_KEY: cleanups,
        REPORT_KEY: report,
    }
    try:
        result = run_task(
            spec,
            request,
            services=scoped,
            model_factory=model_factory,
            post_override=post_override,
        )
    finally:
        run_cleanups(cleanups)
    return _with_facts(result, report)


def run_cleanups(callbacks: list[Callable[[], None]]) -> None:
    while callbacks:
        callback = callbacks.pop()
        try:
            callback()
        except Exception as exc:
            _logger.warning("pam cleanup failed: %s", type(exc).__name__)


def _initial_report(request: InvocationRequest) -> dict[str, Any]:
    mode = "implementer" if request.mode is Mode.IMPLEMENTER else "advisor"
    return {
        "mode": mode,
        "branch": None,
        "mr_url": None,
        "checks": [],
        "files_changed": [],
        "protected_paths_touched": [],
    }


def _with_facts(result: InvocationResult, report: dict[str, Any]) -> InvocationResult:
    """Facts come from the session, never from the model's own claims."""
    data: dict[str, Any] = {**result.data}
    data.update({key: report[key] for key in FACT_KEYS})
    data.setdefault("plan", [])
    warnings = list(result.warnings)
    status = result.status
    verdict = result.verdict
    halt = report.get("halt")
    if isinstance(halt, str):
        warnings.append(f"run halted: {halt}")
        if status is RunStatus.COMPLETE:
            status = RunStatus.INCOMPLETE
            verdict = Verdict.INCOMPLETE
    elif report["mode"] == "implementer" and report["mr_url"] is None:
        if status is RunStatus.COMPLETE:
            warnings.append("no change request was opened")
    return result.model_copy(
        update={
            "status": status,
            "verdict": verdict,
            "data": data,
            "warnings": warnings,
        }
    )
