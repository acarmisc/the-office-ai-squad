from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from code_squad._common.config.schema import ImplementerConfig
from code_squad._common.contract import RunStatus
from code_squad._common.fake_model import ScriptedModel
from code_squad._common.sandbox.env import SAFE_PATH
from tests.pam.support import (
    BASE_FILES,
    GREETING,
    MAKEFILE,
    call,
    finish_call,
    has_node,
    make_harness,
    results_of,
    run,
)

NODE_PACKAGE = """{
  "name": "tiny-app",
  "version": "1.0.0",
  "scripts": {
    "lint": "node -e \\"console.log('lint ok')\\"",
    "test": "node -e \\"console.log('test ok')\\""
  }
}
"""
NODE_LOCK = (
    '{"name": "tiny-app", "version": "1.0.0", "lockfileVersion": 3, '
    '"requires": true, "packages": {"": {"name": "tiny-app", "version": "1.0.0"}}}\n'
)
PATCH = "--- a/README.md\n+++ b/README.md\n@@ -1 +1,2 @@\n tiny app\n+more text\n"


def test_node_checks_install_locked_then_run_scripts_offline(tmp_path: Path) -> None:
    if not has_node():
        pytest.skip("node and npm are not installed")
    node_dir = os.path.dirname(shutil.which("node") or "")
    files = {
        **BASE_FILES,
        "package.json": NODE_PACKAGE,
        "package-lock.json": NODE_LOCK,
    }
    harness = make_harness(tmp_path, files, path_value=f"{SAFE_PATH}:{node_dir}")
    model = ScriptedModel(
        [
            call("start_work", task_key="ENG-1", summary="Add greeting"),
            call("write_file", path="src/greeting.js", content=GREETING),
            call("run_checks"),
            call("commit", message="add greeting"),
            finish_call("checks run", ["Run the checks"]),
        ]
    )
    result = run(harness, [model])

    assert result.data["checks"] == [
        {"name": "npm ci", "passed": True, "exit_code": 0},
        {"name": "npm run lint", "passed": True, "exit_code": 0},
        {"name": "npm run test", "passed": True, "exit_code": 0},
    ]
    assert result.status is RunStatus.COMPLETE


def test_failing_check_is_reported_with_its_exit_code(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, {**BASE_FILES, "Makefile": MAKEFILE})
    config = ImplementerConfig(check_commands=["git status --short", "make no-such"])
    model = ScriptedModel(
        [
            call("start_work", task_key="ENG-1", summary="Add greeting"),
            call("run_checks"),
            finish_call("a check fails", []),
        ]
    )
    result = run(harness, [model], config=config)

    text = results_of(model)[1]
    assert "1/2 steps passed" in text
    assert "FAIL make no-such (exit 2)" in text
    assert "PASS git status --short (exit 0)" in text
    assert result.data["checks"] == [
        {"name": "git status --short", "passed": True, "exit_code": 0},
        {"name": "make no-such", "passed": False, "exit_code": 2},
    ]


def test_run_checks_reports_when_nothing_is_configured(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, BASE_FILES)
    model = ScriptedModel(
        [
            call("start_work", task_key="ENG-1", summary="x"),
            call("run_checks"),
            finish_call("no checks", []),
        ]
    )
    result = run(harness, [model])
    assert "No checks were detected" in results_of(model)[1]
    assert result.data["checks"] == []


def test_sandbox_list_shows_committed_and_untracked_entries(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, {**BASE_FILES, "Makefile": MAKEFILE})
    model = ScriptedModel(
        [
            call("start_work", task_key="ENG-1", summary="x"),
            call("write_file", path="src/feature/card.js", content="x\n"),
            call("sandbox_list", path="src"),
            finish_call("listed", []),
        ]
    )
    run(harness, [model])
    listing = results_of(model)[2]
    assert "app.js" in listing
    assert "feature" in listing


def test_sandbox_list_refuses_a_file_and_traversal(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, {**BASE_FILES, "Makefile": MAKEFILE})
    model = ScriptedModel(
        [
            call("start_work", task_key="ENG-1", summary="x"),
            call("sandbox_list", path="README.md"),
            call("sandbox_list", path="../etc"),
            finish_call("done", []),
        ]
    )
    run(harness, [model])
    texts = results_of(model)
    assert "not a directory: README.md" in texts[1]
    assert "refused" in texts[2]


def test_apply_patch_then_sandbox_diff_shows_the_change(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, {**BASE_FILES, "Makefile": MAKEFILE})
    model = ScriptedModel(
        [
            call("start_work", task_key="ENG-1", summary="x"),
            call("apply_patch", patch=PATCH),
            call("sandbox_diff"),
            finish_call("patched", []),
        ]
    )
    run(harness, [model])
    assert "+more text" in results_of(model)[2]


def test_commit_without_changes_says_so(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, {**BASE_FILES, "Makefile": MAKEFILE})
    model = ScriptedModel(
        [
            call("start_work", task_key="ENG-1", summary="x"),
            call("commit", message="noop"),
            finish_call("nothing", []),
        ]
    )
    result = run(harness, [model])
    assert "nothing to commit" in results_of(model)[1]
    assert result.data["files_changed"] == []


def test_commit_before_start_work_is_refused(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, {**BASE_FILES, "Makefile": MAKEFILE})
    model = ScriptedModel(
        [
            call("commit", message="early"),
            finish_call("stopped", []),
        ]
    )
    run(harness, [model])
    assert "call start_work first" in results_of(model)[0]
    assert harness.created == []


def test_run_command_refuses_shells_and_unlisted_executables(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, {**BASE_FILES, "Makefile": MAKEFILE})
    model = ScriptedModel(
        [
            call("start_work", task_key="ENG-1", summary="x"),
            call("run_command", argv=["sh", "-c", "echo hi"]),
            call("run_command", argv=["curl", "https://example.invalid"]),
            finish_call("done", []),
        ]
    )
    run(harness, [model])
    texts = results_of(model)
    assert "refused" in texts[1]
    assert "refused" in texts[2]
