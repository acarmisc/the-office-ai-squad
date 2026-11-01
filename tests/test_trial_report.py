from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.trial_report import (
    exit_code,
    main,
    parse_result,
    render,
    severity_counts,
)

_RESULT: dict[str, object] = {
    "agent": "michael",
    "status": "complete",
    "verdict": "request_changes",
    "summary": "Checked the change.",
    "findings": [
        {"severity": "blocker"},
        {"severity": "major"},
        {"severity": "major"},
        {"severity": "nit"},
    ],
    "stats": {
        "iterations": 4,
        "input_tokens": 1200,
        "output_tokens": 340,
        "tool_calls": {"get_review_context": 1},
    },
    "posted": {"notes": 0, "discussions": 0, "status": None, "urls": []},
    "warnings": ["2 file(s) not reviewed (truncated or binary)"],
}


def test_severity_counts_lists_every_level_in_order_and_unknowns_last() -> None:
    counts = severity_counts(
        [{"severity": "nit"}, {"severity": "blocker"}, {"severity": "odd"}]
    )
    assert list(counts) == ["blocker", "major", "minor", "nit", "odd"]
    assert counts["blocker"] == 1
    assert counts["major"] == 0
    assert counts["odd"] == 1


def test_render_shows_verdict_counts_tokens_and_wall_time() -> None:
    text = render(_RESULT, 12.34)
    assert "verdict:  request_changes" in text
    assert "blocker 1, major 2, minor 0, nit 1" in text
    assert "input=1200 output=340" in text
    assert "wall:     12.3 s" in text
    assert "  - 2 file(s) not reviewed (truncated or binary)" in text


def test_render_without_wall_time_or_warnings_says_so() -> None:
    data = dict(_RESULT, warnings=[], findings=[])
    text = render(data, None)
    assert "wall:" not in text
    assert text.endswith("warnings:\n  none")


def test_failed_status_exits_non_zero_and_other_statuses_do_not() -> None:
    assert exit_code({"status": "failed"}) == 1
    assert exit_code({"status": "complete"}) == 0
    assert exit_code({"status": "incomplete"}) == 0


def test_parse_result_refuses_a_non_object() -> None:
    with pytest.raises(ValueError):
        parse_result("[1, 2]")


def test_main_reads_a_file_and_returns_the_status_exit_code(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text(json.dumps(_RESULT), encoding="utf-8")
    assert main([str(path), "--wall-seconds", "3"]) == 0
    failed = tmp_path / "failed.json"
    failed.write_text(json.dumps(dict(_RESULT, status="failed")), encoding="utf-8")
    assert main([str(failed)]) == 1


def test_main_rejects_bad_arguments_and_bad_json(tmp_path: Path) -> None:
    assert main([]) == 2
    assert main(["x.json", "--wall-seconds"]) == 2
    broken = tmp_path / "broken.json"
    broken.write_text("not json", encoding="utf-8")
    assert main([str(broken)]) == 1


def test_render_lists_top_findings() -> None:
    from scripts.trial_report import render

    finding = {
        "severity": "major",
        "confidence": "high",
        "agent": "jim",
        "rule_id": "REACT-HOOKS-001",
        "file": "src/App.tsx",
        "line_start": 12,
        "title": "Effect without cleanup",
    }
    text = render({"agent": "michael", "findings": [finding]}, None)
    assert "top findings:" in text
    assert "REACT-HOOKS-001 src/App.tsx:12 Effect without cleanup" in text
