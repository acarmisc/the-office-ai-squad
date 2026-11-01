"""Michael's publication: the shared findings pipeline fed with the consolidated report.

Nothing about anchoring, dedupe, verdicts or rendering lives here. The consolidated
report supplies the findings, their contributors, the agents that did not complete and
the verdict floor; ``findings.publish`` decides the rest.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from code_squad._common.contract import Posted
from code_squad._common.findings import PublishOptions, PublishOutcome, publish
from code_squad._common.posting import DryRunError, PostingGate
from code_squad._common.vcs.base import ChangeRequestRef, VcsProvider
from code_squad.michael.aggregate import ConsolidatedReport

DEFAULT_CONTEXT: Final = "ai-review/michael"


def publish_consolidated(
    provider: VcsProvider,
    ref: ChangeRequestRef,
    report: ConsolidatedReport,
    summary: str,
    *,
    gate: PostingGate,
    options: PublishOptions,
    config_notes: Sequence[str] = (),
) -> PublishOutcome:
    try:
        return publish(
            provider,
            ref,
            report.head_sha,
            report.findings,
            summary,
            agent="michael",
            gate=gate,
            options=options,
            contributors=report.contributors,
            incomplete=report.failed,
            verdict_floor=report.floor,
            config_notes=config_notes,
        )
    except DryRunError:
        return PublishOutcome(Posted(), (), report.verdict)
