"""Result guards for dwight: the offline verdict guard and the accepted-risk filter.

The runtime applies each guard to the finished result, in order. A guard can only weaken
a result: it drops accepted findings, withholds an approval, or marks the result
incomplete. It never raises a verdict.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any, Final

from code_squad._common.accepted_risks import accepted_risk_filter
from code_squad._common.config.schema import AcceptedRisk
from code_squad._common.contract import InvocationResult, RunStatus, Verdict
from code_squad.dwight.deps.parsers import is_manifest
from code_squad.dwight.tools import INCOMPLETE_FLAG, RepoFiles

ResultGuard = Callable[[InvocationResult, Mapping[str, Any]], InvocationResult]
LOOKUP_TOOLS: Final = ("lookup_vulnerabilities", "lookup_cve", "search_advisories")
UNVERIFIED: Final = "vulnerability data unavailable/unverified"
APPROVE_WITHHELD: Final = f"{UNVERIFIED}; approve withheld"
INCOMPLETE_NOTE: Final = f"{UNVERIFIED}; result marked incomplete"
_FAIL_INCOMPLETE: Final = "fail_incomplete"


def offline_verdict_guard(
    result: InvocationResult, services: Mapping[str, Any]
) -> InvocationResult:
    if not _degraded(result, services):
        return result
    if services.get("offline_mode") == _FAIL_INCOMPLETE:
        return _mark_incomplete(result)
    if result.verdict is not Verdict.APPROVE:
        return _note(result, UNVERIFIED)
    return result.model_copy(
        update={
            "verdict": Verdict.COMMENT,
            "warnings": _with_new(result.warnings, [APPROVE_WITHHELD]),
        }
    )


def accepted_risk_guard(
    result: InvocationResult, services: Mapping[str, Any]
) -> InvocationResult:
    """Drop findings an organisation risk accepts, within its package and path scope."""
    keep = accepted_risk_filter(_risks(services.get("accepted_risks")), date.today())
    kept, notes = keep(result.findings)
    if not notes:
        return result
    return result.model_copy(
        update={"findings": kept, "warnings": _with_new(result.warnings, notes)}
    )


def unverified(services: Mapping[str, Any], tool_calls: Mapping[str, int]) -> bool:
    """True when a dependency change lacks verified vulnerability data.

    Shared by the post-run guard and the publish-time verdict cap (ADR 0009), so both
    apply the same rule.
    """
    if not _touches_manifests(services):
        return False
    if services.get(INCOMPLETE_FLAG) is True:
        return True
    return not any(tool_calls.get(name) for name in LOOKUP_TOOLS)


def _degraded(result: InvocationResult, services: Mapping[str, Any]) -> bool:
    return unverified(services, result.stats.tool_calls)


def _touches_manifests(services: Mapping[str, Any]) -> bool:
    repo = services.get("repo_files")
    if not isinstance(repo, RepoFiles):
        return True
    changed = repo.changed_files()
    if not changed:
        return True
    return any(is_manifest(path) for path in changed)


def _mark_incomplete(result: InvocationResult) -> InvocationResult:
    if result.status is not RunStatus.COMPLETE:
        return result
    return result.model_copy(
        update={
            "status": RunStatus.INCOMPLETE,
            "verdict": Verdict.INCOMPLETE,
            "warnings": _with_new(result.warnings, [INCOMPLETE_NOTE]),
        }
    )


def _note(result: InvocationResult, text: str) -> InvocationResult:
    return result.model_copy(update={"warnings": _with_new(result.warnings, [text])})


def _with_new(existing: Sequence[str], new: Sequence[str]) -> list[str]:
    """Appends each warning once, so a guard that runs again adds no duplicate."""
    merged = list(existing)
    for text in new:
        if text not in merged:
            merged.append(text)
    return merged


def _risks(value: object) -> tuple[AcceptedRisk, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    return tuple(item for item in value if isinstance(item, AcceptedRisk))
