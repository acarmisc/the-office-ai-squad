"""CI/CD helpers over the VcsProvider interface. Read only."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Final

from code_squad._common.vcs.base import CiJob, CiRun, VcsProvider

FAILED_STATUSES: Final = frozenset({"failed", "failure", "error", "timed_out"})
MAX_RAW_LOG_BYTES: Final = 500_000
CONTEXT_LINES: Final = 40
MAX_FAILURE_REGIONS: Final = 3
MERGED_CHANGES_NOTE: Final = (
    "not supported by provider interface: the VCS interface has no operation to list "
    "merged change requests, so merged changes cannot be correlated with the symptom"
)
_FAILURE_LINE: Final = re.compile(
    r"(?i)\b(?:error|failed|failure|exception|fatal|traceback|panic)\b"
    r"|exit (?:code|status)[: ]+[1-9]|exited with (?:code )?[1-9]"
)


def recent_runs(
    provider: VcsProvider, project: str, ref: str, limit: int = 10
) -> list[CiRun]:
    return provider.list_ci_runs(project, ref)[:limit]


def failed_jobs(provider: VcsProvider, project: str, run_id: str) -> list[CiJob]:
    return [
        job
        for job in provider.list_ci_jobs(project, run_id)
        if job.status in FAILED_STATUSES
    ]


def job_log_failure_region(
    provider: VcsProvider, project: str, job_id: str, max_bytes: int
) -> str:
    raw = provider.get_job_log(project, job_id, MAX_RAW_LOG_BYTES)
    return failure_region(raw, max_bytes)


def failure_region(text: str, max_bytes: int) -> str:
    """Keep the last failure lines with context, plus the tail of the log.

    The last ``MAX_FAILURE_REGIONS`` matching lines each keep ``CONTEXT_LINES`` lines
    on both sides. Gaps are marked. The result is cut to ``max_bytes`` from the end.
    """
    lines = text.splitlines()
    if not lines or max_bytes <= 0:
        return ""
    hits = [index for index, line in enumerate(lines) if _FAILURE_LINE.search(line)]
    keep: set[int] = set(range(max(0, len(lines) - CONTEXT_LINES), len(lines)))
    for index in hits[-MAX_FAILURE_REGIONS:]:
        low = max(0, index - CONTEXT_LINES)
        high = min(len(lines), index + CONTEXT_LINES + 1)
        keep.update(range(low, high))
    pieces: list[str] = []
    previous = -1
    for index in sorted(keep):
        gap = index - previous - 1
        if gap > 0:
            pieces.append(f"... {gap} lines omitted ...")
        pieces.append(lines[index])
        previous = index
    result = "\n".join(pieces)
    encoded = result.encode("utf-8")
    if len(encoded) > max_bytes:
        result = encoded[-max_bytes:].decode("utf-8", errors="ignore")
    return result


def recent_merged_changes(provider: VcsProvider, project: str, since: datetime) -> str:
    """Return the merged-change note: the VCS protocol cannot list merged changes."""
    del provider, project, since
    return MERGED_CHANGES_NOTE
