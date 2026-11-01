from __future__ import annotations

from datetime import UTC, datetime

from code_squad._common.vcs.base import CiJob, CiRun
from code_squad._common.vcs.fake import FakeVcsProvider
from code_squad.darryl import ci

PROJECT = "acme/web"


def _long_log(error_at: int, total: int = 1000) -> str:
    lines = [f"step line {i}" for i in range(total)]
    lines[error_at] = "ERROR: integration test failed with exit code 2"
    return "\n".join(lines) + "\n"


def test_failure_region_keeps_error_context_and_tail_and_marks_gaps() -> None:
    log = _long_log(error_at=500)
    region = ci.failure_region(log, max_bytes=100_000)
    assert "ERROR: integration test failed with exit code 2" in region
    assert "step line 460" in region
    assert "step line 540" in region
    assert "step line 999" in region
    assert "step line 100\n" not in region + "\n"
    assert "lines omitted" in region


def test_failure_region_uses_the_last_matching_lines() -> None:
    lines = [f"step line {i}" for i in range(2000)]
    lines[100] = "early FAILED marker"
    lines[1900] = "late FATAL marker"
    region = ci.failure_region("\n".join(lines), max_bytes=100_000)
    assert "late FATAL marker" in region
    assert "early FAILED marker" in region


def test_failure_region_small_log_is_returned_whole() -> None:
    log = "line a\nline b\nERROR boom\n"
    assert ci.failure_region(log, max_bytes=1000) == "line a\nline b\nERROR boom"


def test_failure_region_without_matches_returns_tail_only() -> None:
    lines = [f"ok {i}" for i in range(500)]
    region = ci.failure_region("\n".join(lines), max_bytes=100_000)
    assert "ok 499" in region
    assert "ok 10\n" not in region + "\n"


def test_failure_region_is_cut_to_max_bytes_from_the_end() -> None:
    log = _long_log(error_at=990)
    region = ci.failure_region(log, max_bytes=200)
    assert len(region.encode("utf-8")) <= 200
    assert "step line 999" in region


def test_failure_region_of_empty_log_is_empty() -> None:
    assert ci.failure_region("", max_bytes=100) == ""
    assert ci.failure_region("abc", max_bytes=0) == ""


def _provider() -> FakeVcsProvider:
    fake = FakeVcsProvider()
    fake.add_ci_run(
        PROJECT,
        CiRun(
            id="5001",
            status="failed",
            ref="main",
            sha="c" * 40,
            web_url="https://ci.example.test/5001",
            name="pipeline",
        ),
        jobs=[
            CiJob(id="7001", name="unit", status="success", stage="test", web_url=""),
            CiJob(
                id="7002", name="integration", status="failed", stage="test", web_url=""
            ),
            CiJob(
                id="7003", name="deploy", status="canceled", stage="deploy", web_url=""
            ),
        ],
        logs={"7002": _long_log(error_at=600)},
    )
    return fake


def test_failed_jobs_lists_only_failing_jobs() -> None:
    jobs = ci.failed_jobs(_provider(), PROJECT, "5001")
    assert [job.name for job in jobs] == ["integration"]


def test_job_log_failure_region_reads_through_the_provider() -> None:
    region = ci.job_log_failure_region(_provider(), PROJECT, "7002", max_bytes=50_000)
    assert "ERROR: integration test failed" in region
    assert "step line 10\n" not in region + "\n"


def test_recent_runs_respects_the_limit() -> None:
    fake = FakeVcsProvider()
    for number in range(12):
        fake.add_ci_run(
            PROJECT,
            CiRun(
                id=str(900 + number),
                status="success",
                ref="main",
                sha="d" * 40,
                web_url="",
                name=f"run {number}",
            ),
        )
    runs = ci.recent_runs(fake, PROJECT, "main", limit=5)
    assert len(runs) == 5


def test_merged_changes_report_the_missing_provider_operation() -> None:
    note = ci.recent_merged_changes(
        FakeVcsProvider(), PROJECT, datetime(2026, 11, 1, tzinfo=UTC)
    )
    assert note.startswith("not supported by provider interface")
    assert "merged change requests" in note
