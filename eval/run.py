"""Evaluation runner: replays scripted outputs (default) or drives the live model.

Every case seeds a fake VCS provider with the fixture repository and the seeded change,
then runs the real agent in dry-run through ``ServiceBuilder``, ``plan_run`` and
``run_task``. Replay mode uses the scripted model in ``eval/replays``; it exercises the
pipeline and the scorers, and it measures nothing about model quality. Live mode needs
``EVAL_LIVE=1`` and ``LLM_BASE_URL``. It never writes to a real VCS.

    python -m eval.run                 # replay, writes eval/reports/report.md
    EVAL_LIVE=1 LLM_BASE_URL=... python -m eval.run --live
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_squad._common.config.loader import ConfigSources
from code_squad._common.contract import InvocationRequest, InvocationResult, Mode
from code_squad._common.fake_model import ScriptedModel
from code_squad._common.model import ModelFactory, get_model_factory
from code_squad._common.registry import get_spec
from code_squad._common.runtime import run_task
from code_squad._common.services import ServiceBuilder, plan_run
from code_squad._common.vcs.base import ChangeRequest, ChangeRequestRef
from code_squad._common.vcs.fake import FAKE_TOKEN, FakeVcsProvider
from eval.cases import GoldenCase, load_cases
from eval.scorers import Aggregate, CaseScore, aggregate, score_case

ROOT: Path = Path(__file__).resolve().parent
ENV: dict[str, str] = {
    "VCS_PROVIDER": "github",
    "VCS_BASE_URL": "https://api.github.com",
}


class _EvalSecrets:
    def get(self, name: str) -> str:
        if name != "vcs-token":
            raise KeyError(name)
        return FAKE_TOKEN


@dataclass(frozen=True)
class RunRecord:
    case: GoldenCase
    result: InvocationResult
    writes: int


def _fixture_files(fixture: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(fixture.rglob("*")):
        if path.is_file():
            files[path.relative_to(fixture).as_posix()] = path.read_text(
                encoding="utf-8"
            )
    return files


def _new_file_patch(text: str) -> str:
    lines = text.rstrip("\n").split("\n")
    body = "\n".join(f"+{line}" for line in lines)
    return f"@@ -0,0 +1,{len(lines)} @@\n{body}"


def seeded_provider(case: GoldenCase, fixtures: Path) -> FakeVcsProvider:
    files = _fixture_files(fixtures / case.fixture)
    missing = [path for path in case.added_files if path not in files]
    if missing:
        raise ValueError(f"case {case.id}: added files not in fixture: {missing}")
    ref = ChangeRequestRef(case.project, int(case.target))
    change = ChangeRequest(
        ref=ref,
        title=case.title,
        description="Evaluation change request.",
        author="eval-author",
        source_branch="eval/change",
        target_branch="main",
        head_sha=case.head_sha,
        base_sha=case.base_sha,
        draft=False,
        is_fork=False,
        web_url=f"https://fake.invalid/{case.project}/-/pull/{case.target}",
        labels=(),
        state="opened",
    )
    fake = FakeVcsProvider(name="github")
    fake.add_change_request(
        change,
        files={path: _new_file_patch(files[path]) for path in case.added_files},
        file_contents={path: files[path] for path in case.added_files},
    )
    fake.set_files(case.project, files)
    fake.set_default_branch(case.project, "main")
    return fake


def run_case(
    case: GoldenCase,
    *,
    fixtures: Path,
    replays: Path,
    model_factory: ModelFactory | None,
) -> RunRecord:
    fake = seeded_provider(case, fixtures)
    builder = ServiceBuilder(
        provider_factory=lambda _settings: fake,
        secret_provider=_EvalSecrets(),
        config_sources=ConfigSources(None, {}, None, None),
        env=dict(ENV),
    )
    request = InvocationRequest(
        prompt=f"Review change request {case.target} in project {case.project}.",
        project=case.project,
        target=case.target,
        mode=Mode.REVIEW,
        post=False,
    )
    services = builder.build(request, case.agent)
    plan = plan_run(get_spec(case.agent), services)
    factory = model_factory or _replay_factory(replays / case.replay)
    result = run_task(
        plan.spec,
        request,
        services=services,
        model_factory=factory,
        post_override=plan.post_override,
    )
    return RunRecord(case=case, result=result, writes=len(fake.writes))


def _replay_factory(path: Path) -> ModelFactory:
    model = ScriptedModel.from_json(path)

    def _factory(*_args: Any) -> ScriptedModel:
        return model

    return _factory


def score(record: RunRecord) -> CaseScore:
    result = record.result
    return score_case(
        record.case,
        result.findings,
        verdict=result.verdict.value,
        summary=result.summary,
        writes=record.writes,
    )


def render_report(mode: str, scores: Sequence[CaseScore], total: Aggregate) -> str:
    lines = [
        "# Evaluation report",
        "",
        f"Mode: **{mode}**. "
        + (
            "Replay uses scripted model outputs: it checks the pipeline and "
            "the scorers, not model quality."
            if mode == "replay"
            else "Live run against the configured model gateway, dry-run only."
        ),
        "",
        "## Aggregate",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Cases | {total.cases} |",
        f"| Recall (seeded issues found) | {total.recall:.2f} |",
        f"| Precision (findings matching a seeded issue) | {total.precision:.2f} |",
        f"| False-blocker rate | {total.false_blocker_rate:.2f} |",
        f"| Injection resistance | {_fmt_optional(total.injection_resistance)} |",
        f"| Must-not-flag hits | {total.must_not_hits} |",
        "",
        "## Cases",
        "",
        "| Case | Expected | Found | Matched | Verdict | External writes | Injection |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in scores:
        lines.append(
            f"| {item.case_id} | {item.expected} | {item.findings} | {item.matched} "
            f"| {item.verdict} | {item.writes} | {_fmt_bool(item.injection_resisted)} |"
        )
    lines.append("")
    for item in scores:
        lines.extend(_details(item))
    return "\n".join(lines) + "\n"


def _details(item: CaseScore) -> list[str]:
    lines = [f"## {item.case_id}", ""]
    lines.append("- Missed: " + ("; ".join(item.missed) or "none"))
    lines.append("- False positives: " + ("; ".join(item.false_positives) or "none"))
    lines.append("- Must-not-flag hits: " + ("; ".join(item.must_not_detail) or "none"))
    lines.append(f"- False blockers: {item.false_blockers} of {item.blockers}")
    lines.append("")
    return lines


def _fmt_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _fmt_bool(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "pass" if value else "fail"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.run", description=__doc__)
    parser.add_argument("--live", action="store_true", help="drive the live model")
    parser.add_argument("--cases", type=Path, default=ROOT / "cases")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "fixtures")
    parser.add_argument("--replays", type=Path, default=ROOT / "replays")
    parser.add_argument("--report", type=Path, default=ROOT / "reports" / "report.md")
    parser.add_argument("--case", action="append", default=[], dest="only")
    args = parser.parse_args(argv)
    live: bool = bool(args.live)
    model_factory: ModelFactory | None = None
    if live:
        problem = _live_problem()
        if problem is not None:
            print(problem, file=sys.stderr)
            return 2
        model_factory = get_model_factory()
    cases = load_cases(Path(args.cases), tuple(args.only))
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2
    records = [
        run_case(
            case,
            fixtures=Path(args.fixtures),
            replays=Path(args.replays),
            model_factory=model_factory,
        )
        for case in cases
    ]
    scores = [score(record) for record in records]
    report = render_report("live" if live else "replay", scores, aggregate(scores))
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"eval: {len(scores)} case(s), report written to {report_path}")
    return 0


def _live_problem() -> str | None:
    if os.environ.get("EVAL_LIVE") != "1":
        return "live evaluation needs EVAL_LIVE=1; nothing was run"
    if not os.environ.get("LLM_BASE_URL"):
        return "live evaluation needs LLM_BASE_URL; nothing was run"
    return None


if __name__ == "__main__":
    sys.exit(main())
