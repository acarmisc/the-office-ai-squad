"""Structure and behaviour of the composite action and of the consumer workflow example.

The summary step is executed for real against a result file, so its output contract is
tested, not just its text.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Final

import yaml

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
ACTION: Final[Path] = ROOT / "action.yml"
EXAMPLE: Final[Path] = ROOT / "examples" / "github" / "github-actions-review-jim.yml"
_INPUT_IN_RUN: Final = re.compile(r"\$\{\{\s*inputs\.")
_SECRET_INPUTS: Final = ("llm-api-key", "github-token")
_IMAGE_TAG: Final = re.compile(r"ghcr\.io/[^\s\"]+:([^\s\"]+)")


def _action() -> dict[str, Any]:
    data = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps() -> list[dict[str, Any]]:
    steps = _action()["runs"]["steps"]
    assert isinstance(steps, list)
    return steps


def _step(step_id: str) -> dict[str, Any]:
    for step in _steps():
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"no step with id {step_id!r}")


def _workflow() -> dict[Any, Any]:
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _run_summary(tmp_path: Path, result: str | None) -> tuple[int, str, str, str]:
    summary = tmp_path / "summary.md"
    output = tmp_path / "output.txt"
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"UV_NATIVE_TLS", "GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"}
    }
    env.update(
        {
            "AGENT": "jim",
            "GITHUB_STEP_SUMMARY": str(summary),
            "GITHUB_OUTPUT": str(output),
            "RESULT_FILE": "",
        }
    )
    if result is not None:
        path = tmp_path / "squad-result.json"
        path.write_text(result, encoding="utf-8")
        env["RESULT_FILE"] = str(path)
    else:
        env["RESULT_FILE"] = str(tmp_path / "missing.json")
    script = _step("summary")["run"]
    completed = subprocess.run(
        ["bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    summary_text = summary.read_text(encoding="utf-8") if summary.exists() else ""
    output_text = output.read_text(encoding="utf-8") if output.exists() else ""
    return completed.returncode, summary_text, output_text, completed.stderr


_RESULT: Final = {
    "agent": "jim",
    "status": "complete",
    "verdict": "request_changes",
    "summary": "Two issues | found.",
    "findings": [
        {"severity": "nit", "file": "a.tsx", "line_start": 3, "title": "Naming"},
        {
            "severity": "blocker",
            "file": "src/B.tsx",
            "line_start": 12,
            "title": "Unsanitised | HTML `here`",
        },
    ],
    "stats": {"input_tokens": 10, "output_tokens": 4},
    "posted": {"notes": 0, "discussions": 0, "status": None},
    "warnings": ["skill x dropped"],
}


def test_action_is_a_composite_whose_steps_all_use_bash() -> None:
    data = _action()
    assert data["runs"]["using"] == "composite"
    assert "image" not in data["runs"]
    for step in _steps():
        assert step.get("shell") == "bash", step.get("name")


def test_review_step_runs_the_image_as_the_job_user_with_a_read_only_root() -> None:
    run = _step("review")["run"]
    assert "docker run --rm" in run
    assert '--user "$(id -u):$(id -g)"' in run
    assert "--read-only" in run
    assert "--entrypoint squad" in run
    assert "ci review" in run


def test_secrets_reach_the_container_by_name_only() -> None:
    run = _step("review")["run"]
    for name in ("GITHUB_TOKEN", "LLM_BASE_URL", "LLM_API_KEY"):
        assert f"-e {name} " in run or f"-e {name} \\" in run, name
        assert f"-e {name}=" not in run, name
    env = _step("review")["env"]
    assert env["LLM_API_KEY"] == "${{ inputs.llm-api-key }}"
    assert env["GITHUB_TOKEN"] == "${{ inputs.github-token }}"


def test_no_run_block_interpolates_an_input_directly() -> None:
    for step in _steps():
        assert not _INPUT_IN_RUN.search(str(step.get("run", ""))), step.get("name")


def test_secret_inputs_are_only_referenced_in_env_blocks() -> None:
    for step in _steps():
        run = str(step.get("run", ""))
        for name in _SECRET_INPUTS:
            assert f"inputs.{name}" not in run, (step.get("name"), name)


def test_the_action_never_checks_out_code() -> None:
    for step in _steps():
        assert "checkout" not in str(step.get("uses", "")), step.get("name")


def test_outputs_are_declared_and_come_from_the_summary_step() -> None:
    outputs = _action()["outputs"]
    assert set(outputs) == {"verdict", "status", "findings", "result-file"}
    for name, spec in outputs.items():
        assert spec["value"].startswith("${{ steps.summary.outputs."), name


def test_summary_step_runs_even_when_the_review_failed() -> None:
    assert _step("summary")["if"] == "always()"


def test_the_default_image_tag_is_the_package_version() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    image = _action()["inputs"]["image"]["default"]
    match = _IMAGE_TAG.fullmatch(image)
    assert match is not None, image
    assert match.group(1) == pyproject["project"]["version"]


def test_the_summary_writes_outputs_and_a_table_for_a_result(tmp_path: Path) -> None:
    code, summary, output, stderr = _run_summary(tmp_path, json.dumps(_RESULT))
    assert code == 0, stderr
    assert "verdict=request_changes" in output
    assert "status=complete" in output
    assert "findings=2" in output
    assert f"result-file={tmp_path / 'squad-result.json'}" in output
    assert "| Severity | Location | Title |" in summary
    assert "| blocker | `src/B.tsx:12` | Unsanitised \\| HTML 'here' |" in summary
    assert summary.index("blocker") < summary.index("nit"), "blocker sorts first"
    assert "skill x dropped" in summary


def test_the_summary_says_so_when_no_result_exists(tmp_path: Path) -> None:
    code, summary, output, stderr = _run_summary(tmp_path, None)
    assert code == 0, stderr
    assert "No review result was written" in summary
    assert "verdict=none" in output
    assert "result-file=\n" in output


def test_the_summary_tolerates_unknown_verdict_tokens(tmp_path: Path) -> None:
    hostile = dict(_RESULT, verdict="approve\nstatus=failed")
    code, _summary, output, _stderr = _run_summary(tmp_path, json.dumps(hostile))
    assert code == 0
    assert "verdict=unknown" in output
    assert "status=failed" not in output


def test_example_workflow_listens_to_pull_requests_only() -> None:
    workflow = _workflow()
    triggers: dict[str, Any] = workflow[True] if True in workflow else workflow["on"]
    assert set(triggers) == {"pull_request"}
    assert "pull_request_target" not in EXAMPLE.read_text(encoding="utf-8")
    types = set(triggers["pull_request"]["types"])
    assert types == {"opened", "synchronize", "reopened", "ready_for_review"}


def test_example_workflow_has_the_listed_permissions_and_a_draft_guard() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
        "statuses": "write",
    }
    job = workflow["jobs"]["review"]
    assert job["if"] == "github.event.pull_request.draft == false"


def test_example_workflow_cancels_superseded_reviews_per_pull_request() -> None:
    concurrency = _workflow()["concurrency"]
    assert "github.event.pull_request.number" in concurrency["group"]
    assert concurrency["cancel-in-progress"] is True


def test_example_workflow_uses_the_action_with_dry_run_by_default() -> None:
    steps = _workflow()["jobs"]["review"]["steps"]
    uses = [step for step in steps if str(step.get("uses", "")).startswith("acarmisc/")]
    assert len(uses) == 1
    with_ = uses[0]["with"]
    assert with_["agent"] == "jim"
    assert with_["post"] == "${{ vars.SQUAD_POST == 'true' && 'true' || 'false' }}"
    assert with_["llm-api-key"] == "${{ secrets.LLM_API_KEY }}"
    assert with_["llm-base-url"] == "${{ vars.LLM_BASE_URL }}"


def test_example_workflow_never_checks_out_the_pull_request() -> None:
    for step in _workflow()["jobs"]["review"]["steps"]:
        if str(step.get("uses", "")).startswith("actions/checkout"):
            assert "ref" not in step.get("with", {}) or "head" not in str(
                step["with"]["ref"]
            )
            assert "repository" in step["with"]
