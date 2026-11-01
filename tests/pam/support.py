from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_squad._common.config.schema import ImplementerConfig
from code_squad._common.contract import InvocationRequest, InvocationResult
from code_squad._common.fake_model import ScriptedModel, Text, ToolCall, Turn
from code_squad._common.sandbox import LocalProcessSandbox
from code_squad._common.sandbox.env import SAFE_PATH, GitIdentity
from code_squad._common.vcs.base import Issue
from code_squad._common.vcs.fake import FakeVcsProvider
from code_squad.pam import SPEC
from code_squad.pam.runner import run_pam
from tests.sandbox.support import run_git
from tests.support import factory_of, tool_result_texts

PROJECT = "acme/web"
IDENTITY = GitIdentity("Pam Test", "pam@example.test")
GREETING = "export const greeting = 'hello';\n"
BASE_FILES: dict[str, str] = {
    "README.md": "tiny app\n",
    "src/app.js": "export const app = 1;\n",
}
MAKEFILE = "check:\n\ttest -f src/app.js\n"


class LocalVcs(FakeVcsProvider):
    """Fake provider whose clone URL is a local bare repository (file://)."""

    def __init__(self, bare: Path) -> None:
        super().__init__()
        self._bare = bare

    def clone_url(self, project: str) -> str:
        return f"file://{self._bare}"


class FakeTracker:
    name = "fake-jira"

    def __init__(self, issues: Mapping[str, Issue]) -> None:
        self._issues = dict(issues)

    def get_issue(self, key: str) -> Issue:
        return self._issues[key]

    def comment_on_issue(self, key: str, body: str) -> str:
        raise AssertionError("pam never comments through the tracker")


def seed_bare_repo(root: Path, files: Mapping[str, str]) -> Path:
    """A bare repository whose main branch holds the given files."""
    work = root / "work"
    work.mkdir(parents=True)
    run_git(["init", "-q", "-b", "main"], work)
    for rel, text in files.items():
        target = work / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    run_git(["add", "."], work)
    run_git(["commit", "-q", "-m", "init"], work)
    bare = root / "bare.git"
    run_git(["clone", "-q", "--bare", str(work), str(bare)], root)
    return bare


def issue(number: int, body: str, title: str = "Add a greeting") -> Issue:
    return Issue(
        project=PROJECT,
        number=number,
        title=title,
        body=body,
        labels=("frontend",),
        assignees=(),
        state="open",
        web_url=f"https://fake.invalid/{PROJECT}/-/issues/{number}",
    )


@dataclass
class Harness:
    root: Path
    bare: Path
    workspaces: Path
    provider: LocalVcs
    path_value: str = SAFE_PATH
    created: list[LocalProcessSandbox] = field(default_factory=list)

    def factory(self) -> LocalProcessSandbox:
        sandbox = LocalProcessSandbox(
            workspace_root=self.workspaces,
            allowed_schemes=("file",),
            git_identity=IDENTITY,
            path_value=self.path_value,
        )
        self.created.append(sandbox)
        return sandbox

    def services(
        self,
        config: ImplementerConfig | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        return {
            "vcs": self.provider,
            "sandbox_factory": self.factory,
            "implementer_config": config,
            **extra,
        }

    def branches(self) -> list[str]:
        out = run_git(
            ["for-each-ref", "--format=%(refname:short)", "refs/heads"], self.bare
        )
        return sorted(line for line in out.splitlines() if line)

    def workspace_entries(self) -> list[Path]:
        return sorted(self.workspaces.iterdir()) if self.workspaces.exists() else []


def make_harness(
    tmp_path: Path,
    files: Mapping[str, str] | None = None,
    *,
    path_value: str = SAFE_PATH,
) -> Harness:
    root = tmp_path / "remote"
    root.mkdir()
    chosen = dict(BASE_FILES if files is None else files)
    bare = seed_bare_repo(root, chosen)
    provider = LocalVcs(bare)
    provider.set_files(PROJECT, chosen)
    provider.add_issue(issue(7, "Create src/greeting.js exporting a greeting."))
    workspaces = tmp_path / "workspaces"
    workspaces.mkdir()
    return Harness(
        root=root,
        bare=bare,
        workspaces=workspaces,
        provider=provider,
        path_value=path_value,
    )


def call(name: str, **arguments: Any) -> Turn:
    return Turn((ToolCall(name, dict(arguments)),))


def say(text: str) -> Turn:
    return Turn((Text(text),), stop_reason="end_turn")


def finish_call(summary: str, plan: list[str], verdict: str = "comment") -> Turn:
    return call(
        "finish",
        verdict=verdict,
        summary=summary,
        findings=[],
        data={"plan": plan},
    )


def implementer_request(**overrides: Any) -> InvocationRequest:
    values: dict[str, Any] = {
        "prompt": "Implement the task.",
        "project": PROJECT,
        "target": "#7",
        "mode": "implementer",
        "post": True,
    }
    values.update(overrides)
    return InvocationRequest.model_validate(values)


def advisor_request(**overrides: Any) -> InvocationRequest:
    values: dict[str, Any] = {
        "prompt": "How should I build this?",
        "project": PROJECT,
        "target": "#7",
        "post": True,
    }
    values.update(overrides)
    return InvocationRequest.model_validate(values)


def run(
    harness: Harness,
    models: list[ScriptedModel],
    request: InvocationRequest | None = None,
    *,
    config: ImplementerConfig | None = None,
    services: dict[str, Any] | None = None,
) -> InvocationResult:
    return run_pam(
        SPEC,
        request or implementer_request(),
        services=services if services is not None else harness.services(config),
        model_factory=factory_of(*models),
    )


def results_of(model: ScriptedModel) -> list[str]:
    return tool_result_texts(model.calls[-1].messages) if model.calls else []


def has_node() -> bool:
    return shutil.which("node") is not None and shutil.which("npm") is not None
