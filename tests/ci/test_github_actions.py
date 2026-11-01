"""``squad ci review`` end to end: event, provider fake, scripted model, result file."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from code_squad._common import services as services_module
from code_squad._common.ci import github_actions as gha
from code_squad._common.ci.github_actions import (
    CiUsageError,
    FailOn,
    ReviewOptions,
    bootstrap_env,
    gate_exit_code,
    request_payload,
    run_review,
)
from code_squad._common.cli import app
from code_squad._common.contract import (
    InvocationResult,
    RunStatus,
    Verdict,
)
from code_squad._common.fake_model import ScriptedModel, ToolCall, Turn
from code_squad._common.findings import marker
from code_squad._common.model import set_model_factory
from code_squad._common.vcs.factory import VcsSettings
from code_squad.michael.inprocess import InProcessSpecialistClient
from tests.agents.support import (
    HEAD,
    NUMBER,
    PROJECT,
    REACT_PATH,
    REACT_TEXT,
    comments_with_marker,
    line_of,
    models,
    react_provider,
    writes_of,
)
from tests.support import FAKE_TOKEN, finding_dict, finish_turn

REPO_SKILL = "\n".join(
    [
        "---",
        "name: shared-react",
        "description: Shared conventions for React components",
        "---",
        "Prefer named exports for components.",
        "",
    ]
)


def _pull_request(
    *,
    number: int = NUMBER,
    draft: bool = False,
    head: str = PROJECT,
    base: str = PROJECT,
) -> dict[str, Any]:
    return {
        "action": "opened",
        "pull_request": {
            "number": number,
            "draft": draft,
            "head": {"sha": HEAD, "repo": {"full_name": head}},
            "base": {"sha": "d" * 40, "repo": {"full_name": base}},
        },
    }


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    return path


@pytest.fixture
def event_file(tmp_path: Path) -> Path:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(_pull_request()), encoding="utf-8")
    return path


def _env(workspace: Path, event: Path) -> dict[str, str]:
    return {
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REPOSITORY": PROJECT,
        "GITHUB_API_URL": "https://api.github.com",
        "GITHUB_RUN_ID": "1234",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_WORKSPACE": str(workspace),
        "GITHUB_TOKEN": FAKE_TOKEN,
        "LLM_BASE_URL": "https://llm.invalid/v1",
        "LLM_API_KEY": FAKE_TOKEN,
    }


def _review_script(
    findings: list[dict[str, Any]], verdict: str, skill: str = "react-conventions"
) -> list[Turn]:
    turns = [
        Turn((ToolCall("get_review_context", {}),)),
        Turn((ToolCall("load_skill", {"name": skill}),)),
    ]
    if findings:
        turns.append(
            Turn(
                (ToolCall("publish_review", {"findings": findings, "summary": "Hi."}),)
            )
        )
    turns.append(finish_turn(verdict, "Issues found.", findings))
    return turns


def _finding() -> dict[str, Any]:
    return finding_dict(
        agent="jim",
        head_sha=HEAD,
        file=REACT_PATH,
        category="security",
        rule_id="REACT-SEC-001",
        severity="blocker",
        confidence="high",
        line_start=line_of(REACT_TEXT, "dangerouslySetInnerHTML"),
        line_end=line_of(REACT_TEXT, "dangerouslySetInnerHTML"),
        title="Unsanitised HTML from the profile bio",
        rationale="The bio is rendered without sanitising.",
        failure_scenario="A bio with a script runs in every viewer's session.",
    )


def _provider_factory(
    fake: Any, captured: list[VcsSettings] | None = None
) -> services_module.ProviderFactory:
    def build(settings: VcsSettings) -> Any:
        if captured is not None:
            captured.append(settings)
        return fake

    return build


def _outcome(
    options: ReviewOptions,
    env: dict[str, str],
    model: ScriptedModel,
    fake: Any | None = None,
) -> gha.ReviewOutcome:
    return run_review(
        options,
        env,
        provider_factory=_provider_factory(fake or react_provider()),
        model_factory=models(model),
    )


def _with_skill(workspace: Path) -> None:
    skill_dir = workspace / ".squad-shared" / "react-shared"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(REPO_SKILL, encoding="utf-8")


def test_dry_run_returns_findings_and_writes_nothing(
    workspace: Path, event_file: Path
) -> None:
    fake = react_provider()
    model = ScriptedModel(_review_script([_finding()], "request_changes"))
    outcome = run_review(
        ReviewOptions(post=False),
        _env(workspace, event_file),
        provider_factory=_provider_factory(fake),
        model_factory=models(model),
    )
    result = outcome.result
    assert result is not None
    assert result.status is RunStatus.COMPLETE
    assert result.verdict is Verdict.REQUEST_CHANGES
    assert len(result.findings) == 1
    assert fake.writes == []
    assert "dry-run blocked 1 external write attempt(s)" in result.warnings
    assert result.stats.skills_applied == ["react-conventions"]


def test_post_publishes_inline_comment_summary_and_status(
    workspace: Path, event_file: Path
) -> None:
    fake = react_provider()
    model = ScriptedModel(_review_script([_finding()], "request_changes"))
    outcome = _outcome(
        ReviewOptions(post=True), _env(workspace, event_file), model, fake
    )
    assert outcome.result is not None
    assert outcome.result.verdict is Verdict.REQUEST_CHANGES
    inline = writes_of(fake, "post_inline_comments")
    assert len(inline) == 1 and inline[0]["count"] == 1
    statuses = writes_of(fake, "set_status")
    assert len(statuses) == 1
    assert statuses[0]["context"] == "ai-review/jim"
    assert statuses[0]["state"] == "failed"
    assert len(comments_with_marker(fake, "code-squad:summary:jim")) == 1
    assert len(comments_with_marker(fake, marker(outcome.result.findings[0].id))) == 1


def test_request_carries_the_run_key_skills_and_target(
    workspace: Path, event_file: Path
) -> None:
    model = ScriptedModel(_review_script([], "approve"))
    outcome = _outcome(ReviewOptions(agent="jim"), _env(workspace, event_file), model)
    assert outcome.result is not None
    assert outcome.result.verdict is Verdict.APPROVE
    payload = request_payload(
        NUMBER,
        PROJECT,
        ReviewOptions(agent="jim"),
        {"GITHUB_RUN_ID": "1234", "GITHUB_RUN_ATTEMPT": "2"},
        [],
    )
    assert payload["idempotency_key"] == "gha-1234-2-jim"
    assert payload["target"] == str(NUMBER)
    assert payload["mode"] == "review"
    assert payload["post"] is False
    assert payload["prompt"] == f"Review change request {NUMBER} in project {PROJECT}."


def test_bootstrap_maps_github_api_url_and_token_for_the_project(
    workspace: Path, event_file: Path
) -> None:
    captured: list[VcsSettings] = []
    env = _env(workspace, event_file)
    env["GITHUB_API_URL"] = "https://ghes.example.com/api/v3"
    model = ScriptedModel(_review_script([], "approve"))
    run_review(
        ReviewOptions(),
        env,
        provider_factory=_provider_factory(react_provider(), captured),
        model_factory=models(model),
    )
    assert captured, "the provider factory was not called"
    settings = captured[0]
    assert settings.provider == "github"
    assert settings.base_url == "https://ghes.example.com/api/v3"
    assert settings.token == FAKE_TOKEN


def test_bootstrap_env_overrides_the_vcs_variables_without_mutating_the_input() -> None:
    source = {"VCS_PROVIDER": "gitlab", "VCS_TOKEN": "old", "KEEP": "1"}
    values = bootstrap_env(source, "https://api.github.com", "new-token")
    assert values["VCS_PROVIDER"] == "github"
    assert values["VCS_BASE_URL"] == "https://api.github.com"
    assert values["VCS_TOKEN"] == "new-token"
    assert values["KEEP"] == "1"
    assert source["VCS_PROVIDER"] == "gitlab"


def test_draft_pull_request_is_skipped(workspace: Path, tmp_path: Path) -> None:
    event = tmp_path / "draft.json"
    event.write_text(json.dumps(_pull_request(draft=True)), encoding="utf-8")
    model = ScriptedModel([])
    outcome = _outcome(ReviewOptions(), _env(workspace, event), model)
    assert outcome.result is None
    assert outcome.skipped is not None and "draft" in outcome.skipped
    assert model.calls == []


def test_fork_without_secrets_is_skipped(workspace: Path, tmp_path: Path) -> None:
    event = tmp_path / "fork.json"
    event.write_text(
        json.dumps(_pull_request(head="someone/storefront")), encoding="utf-8"
    )
    env = _env(workspace, event)
    env["LLM_API_KEY"] = ""
    outcome = _outcome(ReviewOptions(), env, ScriptedModel([]))
    assert outcome.result is None
    assert outcome.skipped is not None and "fork" in outcome.skipped


def test_fork_with_a_key_is_reviewed(workspace: Path, tmp_path: Path) -> None:
    event = tmp_path / "fork.json"
    event.write_text(
        json.dumps(_pull_request(head="someone/storefront")), encoding="utf-8"
    )
    model = ScriptedModel(_review_script([], "approve"))
    outcome = _outcome(ReviewOptions(), _env(workspace, event), model)
    assert outcome.result is not None


@pytest.mark.parametrize(
    "payload",
    [
        {"ref": "refs/heads/main", "after": "f" * 40},
        {"pull_request": "not an object"},
        {"pull_request": {"draft": False}},
    ],
)
def test_a_non_pull_request_event_is_a_usage_error(
    workspace: Path, tmp_path: Path, payload: dict[str, Any]
) -> None:
    event = tmp_path / "push.json"
    event.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CiUsageError):
        _outcome(ReviewOptions(), _env(workspace, event), ScriptedModel([]))


def test_a_pull_request_review_event_name_is_refused(
    workspace: Path, event_file: Path
) -> None:
    env = _env(workspace, event_file)
    env["GITHUB_EVENT_NAME"] = "pull_request_review"
    with pytest.raises(CiUsageError, match="pull request event"):
        _outcome(ReviewOptions(), env, ScriptedModel([]))


def test_missing_github_token_is_a_usage_error(
    workspace: Path, event_file: Path
) -> None:
    env = _env(workspace, event_file)
    env["GITHUB_TOKEN"] = ""
    with pytest.raises(CiUsageError, match="GITHUB_TOKEN"):
        _outcome(ReviewOptions(), env, ScriptedModel([]))


def test_missing_llm_settings_are_a_usage_error_on_a_same_repo_pr(
    workspace: Path, event_file: Path
) -> None:
    env = _env(workspace, event_file)
    env["LLM_BASE_URL"] = ""
    with pytest.raises(CiUsageError, match="LLM_BASE_URL"):
        _outcome(ReviewOptions(), env, ScriptedModel([]))


def test_unsupported_agent_is_refused_before_anything_runs(
    workspace: Path, event_file: Path
) -> None:
    with pytest.raises(CiUsageError, match="not available in CI"):
        _outcome(
            ReviewOptions(agent="pam"), _env(workspace, event_file), ScriptedModel([])
        )


def test_skills_path_injects_workspace_skills_as_payload(
    workspace: Path, event_file: Path
) -> None:
    _with_skill(workspace)
    model = ScriptedModel(_review_script([], "approve", skill="shared-react"))
    outcome = _outcome(
        ReviewOptions(skills_path=".squad-shared"),
        _env(workspace, event_file),
        model,
    )
    assert outcome.skills == ("shared-react",)
    assert outcome.result is not None
    assert outcome.result.stats.skills_applied == ["shared-react"]


def test_skills_path_refuses_traversal_and_absolute_paths(
    workspace: Path, event_file: Path, tmp_path: Path
) -> None:
    (tmp_path / "outside").mkdir()
    for path in ("../outside", str(tmp_path / "outside")):
        with pytest.raises(CiUsageError):
            _outcome(
                ReviewOptions(skills_path=path),
                _env(workspace, event_file),
                ScriptedModel([]),
            )


def test_skills_path_refuses_a_symlink_that_leaves_the_workspace(
    workspace: Path, event_file: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "shared").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CiUsageError, match="outside the workspace"):
        _outcome(
            ReviewOptions(skills_path="shared"),
            _env(workspace, event_file),
            ScriptedModel([]),
        )


def test_a_skill_file_that_links_outside_is_skipped_with_a_warning(
    workspace: Path, event_file: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "secret.md"
    outside.write_text(REPO_SKILL, encoding="utf-8")
    folder = workspace / "shared" / "linked"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").symlink_to(outside)
    model = ScriptedModel(_review_script([], "approve"))
    outcome = _outcome(
        ReviewOptions(skills_path="shared"), _env(workspace, event_file), model
    )
    assert outcome.skills == ()
    assert outcome.result is not None
    assert any("outside the workspace" in item for item in outcome.result.warnings)


def test_skills_path_needs_an_existing_directory(
    workspace: Path, event_file: Path
) -> None:
    with pytest.raises(CiUsageError, match="not a directory"):
        _outcome(
            ReviewOptions(skills_path="missing"),
            _env(workspace, event_file),
            ScriptedModel([]),
        )


def test_michael_runs_in_process_with_specialists_forced_to_dry_run(
    workspace: Path, event_file: Path
) -> None:
    fake = react_provider()
    model = ScriptedModel(_review_script([_finding()], "request_changes"))
    outcome = _outcome(
        ReviewOptions(agent="michael", post=True),
        _env(workspace, event_file),
        model,
        fake,
    )
    assert outcome.result is not None
    assert outcome.result.agent == "michael"
    assert [item.agent for item in outcome.result.findings] == ["jim"]
    assert model.calls, "the specialist made no model call"
    inline = writes_of(fake, "post_inline_comments")
    assert [write["count"] for write in inline] == [1]
    statuses = writes_of(fake, "set_status")
    assert [write["context"] for write in statuses] == ["ai-review/michael"]


def test_inprocess_specialist_client_never_publishes(
    workspace: Path, event_file: Path
) -> None:
    fake = react_provider()
    model = ScriptedModel(_review_script([_finding()], "request_changes"))
    client = InProcessSpecialistClient(
        lambda request, agent: _services_for(
            fake, workspace, event_file, request, agent
        ),
        models(model),
    )
    result = client.invoke(
        "jim",
        {
            "prompt": "Review.",
            "project": PROJECT,
            "target": str(NUMBER),
            "mode": "review",
            "post": True,
            "idempotency_key": "x",
        },
        timeout_s=30,
        idempotency_key="x",
        trace_headers={},
    )
    assert result.agent == "jim"
    assert fake.writes == []


def _services_for(
    fake: Any, workspace: Path, event: Path, request: Any, agent: str
) -> dict[str, Any]:
    builder = services_module.ServiceBuilder(
        provider_factory=_provider_factory(fake),
        config_sources=None,
        env=_env(workspace, event),
    )
    return builder.build(request, agent)


@pytest.mark.parametrize(
    ("fail_on", "verdict", "status", "expected"),
    [
        (FailOn.NONE, Verdict.REQUEST_CHANGES, RunStatus.COMPLETE, 0),
        (FailOn.REQUEST_CHANGES, Verdict.REQUEST_CHANGES, RunStatus.COMPLETE, 1),
        (FailOn.REQUEST_CHANGES, Verdict.COMMENT, RunStatus.COMPLETE, 0),
        (FailOn.REQUEST_CHANGES, Verdict.INCOMPLETE, RunStatus.INCOMPLETE, 0),
        (FailOn.INCOMPLETE, Verdict.INCOMPLETE, RunStatus.INCOMPLETE, 1),
        (FailOn.INCOMPLETE, Verdict.APPROVE, RunStatus.INCOMPLETE, 1),
        (FailOn.INCOMPLETE, Verdict.COMMENT, RunStatus.COMPLETE, 0),
        (FailOn.NONE, Verdict.APPROVE, RunStatus.FAILED, 1),
        (FailOn.INCOMPLETE, Verdict.APPROVE, RunStatus.FAILED, 1),
    ],
)
def test_gate_exit_code_per_fail_on(
    fail_on: FailOn, verdict: Verdict, status: RunStatus, expected: int
) -> None:
    result = InvocationResult(agent="jim", status=status, verdict=verdict, summary="x")
    assert gate_exit_code(result, fail_on) == expected


def test_a_failed_model_call_fails_the_run(workspace: Path, event_file: Path) -> None:
    def broken(*_args: Any) -> Any:
        raise RuntimeError("gateway down")

    outcome = run_review(
        ReviewOptions(),
        _env(workspace, event_file),
        provider_factory=_provider_factory(react_provider()),
        model_factory=broken,
    )
    assert outcome.result is not None
    assert outcome.result.status is RunStatus.FAILED
    assert gate_exit_code(outcome.result, FailOn.NONE) == 1


@pytest.fixture
def ci_environ(
    monkeypatch: pytest.MonkeyPatch, workspace: Path, event_file: Path
) -> Iterator[Path]:
    for name in (
        "GITHUB_EVENT_PATH",
        "GITHUB_EVENT_NAME",
        "GITHUB_REPOSITORY",
        "GITHUB_API_URL",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_WORKSPACE",
        "GITHUB_TOKEN",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "VCS_PROVIDER",
        "VCS_BASE_URL",
        "VCS_TOKEN",
        "SQUAD_CONFIG_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in _env(workspace, event_file).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(services_module, "build_provider", lambda _s: react_provider())
    yield workspace
    set_model_factory(None)


def _cli(*args: str) -> Any:
    return CliRunner().invoke(app, ["ci", "review", *args])


def test_cli_writes_the_result_file_and_prints_the_summary(
    ci_environ: Path, tmp_path: Path
) -> None:
    set_model_factory(
        lambda *_a: ScriptedModel(_review_script([_finding()], "comment"))
    )
    result_file = tmp_path / "out" / "squad-result.json"
    outcome = _cli("--result-file", str(result_file))
    assert outcome.exit_code == 0, outcome.output
    data = json.loads(result_file.read_text(encoding="utf-8"))
    assert data["agent"] == "jim"
    assert data["status"] == "complete"
    assert "verdict:  comment" in outcome.output
    assert "result written to" in outcome.output


@pytest.mark.parametrize(
    ("verdict", "fail_on", "code"),
    [
        ("request_changes", "none", 0),
        ("request_changes", "request_changes", 1),
        ("comment", "request_changes", 0),
        ("request_changes", "incomplete", 1),
    ],
)
def test_cli_exit_code_follows_fail_on(
    ci_environ: Path, tmp_path: Path, verdict: str, fail_on: str, code: int
) -> None:
    set_model_factory(lambda *_a: ScriptedModel(_review_script([], verdict)))
    outcome = _cli("--fail-on", fail_on, "--result-file", str(tmp_path / "r.json"))
    assert outcome.exit_code == code, outcome.output


def test_cli_exits_one_when_the_run_failed(ci_environ: Path, tmp_path: Path) -> None:
    def broken(*_args: Any) -> Any:
        raise RuntimeError("gateway down")

    set_model_factory(broken)
    outcome = _cli("--result-file", str(tmp_path / "r.json"))
    assert outcome.exit_code == 1
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["status"] == (
        "failed"
    )


def test_cli_skips_a_draft_with_exit_zero_and_no_result(
    ci_environ: Path, tmp_path: Path
) -> None:
    draft = tmp_path / "draft-event.json"
    draft.write_text(json.dumps(_pull_request(draft=True)), encoding="utf-8")
    monkey = pytest.MonkeyPatch()
    monkey.setenv("GITHUB_EVENT_PATH", str(draft))
    try:
        result_file = tmp_path / "r.json"
        outcome = _cli("--result-file", str(result_file))
    finally:
        monkey.undo()
    assert outcome.exit_code == 0, outcome.output
    assert "skipped:" in outcome.output
    assert not result_file.exists()


def test_cli_exits_two_for_a_non_pull_request_event(
    ci_environ: Path, tmp_path: Path
) -> None:
    push = tmp_path / "push.json"
    push.write_text(json.dumps({"ref": "refs/heads/main"}), encoding="utf-8")
    monkey = pytest.MonkeyPatch()
    monkey.setenv("GITHUB_EVENT_PATH", str(push))
    try:
        outcome = _cli("--result-file", str(tmp_path / "r.json"))
    finally:
        monkey.undo()
    assert outcome.exit_code == 2
    assert "not a pull request event" in outcome.output


def test_cli_exits_two_without_a_token(ci_environ: Path, tmp_path: Path) -> None:
    monkey = pytest.MonkeyPatch()
    monkey.delenv("GITHUB_TOKEN")
    try:
        outcome = _cli("--result-file", str(tmp_path / "r.json"))
    finally:
        monkey.undo()
    assert outcome.exit_code == 2
    assert "GITHUB_TOKEN" in outcome.output


def test_cli_reads_options_from_squad_ci_variables(
    ci_environ: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_model_factory(lambda *_a: ScriptedModel(_review_script([], "approve")))
    monkeypatch.setenv("SQUAD_CI_FAIL_ON", "incomplete")
    monkeypatch.setenv("SQUAD_CI_RESULT_FILE", str(tmp_path / "env.json"))
    outcome = CliRunner().invoke(app, ["ci", "review"])
    assert outcome.exit_code == 0, outcome.output
    assert (tmp_path / "env.json").is_file()


def test_unreachable_github_yields_a_failed_result_not_a_traceback(
    workspace: Path, event_file: Path
) -> None:
    import httpx

    from code_squad._common.vcs.github import GitHubProvider, TokenAuth
    from code_squad._common.vcs.http import HttpClient

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    def build(settings: VcsSettings) -> Any:
        client = httpx.Client(transport=httpx.MockTransport(refuse))
        http = HttpClient(client=client, sleep=lambda _s: None, provider="github")
        return GitHubProvider(settings.base_url, auth=TokenAuth(FAKE_TOKEN), http=http)

    outcome = run_review(
        ReviewOptions(agent="jim"),
        _env(workspace, event_file),
        provider_factory=build,
        model_factory=models(ScriptedModel([finish_turn("comment", "x", [])])),
    )
    assert outcome.result is not None
    assert outcome.result.status == "incomplete"
    assert any("could not be loaded" in w for w in outcome.result.warnings)
    assert outcome.result.verdict != "approve"


def test_dependabot_without_secrets_is_skipped(
    workspace: Path, event_file: Path
) -> None:
    env = _env(workspace, event_file)
    env["LLM_API_KEY"] = ""
    env["GITHUB_ACTOR"] = "dependabot[bot]"
    outcome = run_review(ReviewOptions(agent="jim"), env)
    assert outcome.result is None
    assert outcome.skipped is not None and "Dependabot" in outcome.skipped


def test_failed_result_is_well_formed() -> None:
    result = gha.failed_result("jim", RuntimeError("boom"))
    assert result.status == "failed"
    assert result.warnings == ["run failed: RuntimeError"]
