from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

from code_squad._common.config.schema import ImplementerConfig
from code_squad._common.sandbox import (
    BudgetExceededError,
    GitCredentials,
    LoopDetectedError,
    MonitoredSandbox,
    Sandbox,
    SandboxError,
    TrajectoryMonitor,
)
from code_squad._common.sandbox.base import ExecResult
from code_squad._common.sandbox.output import redact_secrets
from code_squad._common.sandbox.policy import (
    DEFAULT_PROTECTED_BRANCHES,
    check_relpath,
    validate_branch,
)
from code_squad._common.untrusted import wrap_untrusted
from code_squad._common.vcs.base import ChangeRequest, NotFoundError, VcsProvider
from code_squad.pam.workflow import (
    CheckOutcome,
    TaskScope,
    branch_name,
    check_task_key,
    commit_message,
    declares_recipe,
    detect_checks,
    detect_package_manager,
    install_command,
    protected_path_violations,
    protected_paths_touched,
    render_mr_body,
    render_title,
)

VCS_KEY: Final = "vcs"
SANDBOX_FACTORY_KEY: Final = "sandbox_factory"
IMPLEMENTER_CONFIG_KEY: Final = "implementer_config"
ISSUE_TRACKER_KEY: Final = "issue_tracker"
SESSION_KEY: Final = "pam_session"
CLEANUP_KEY: Final = "cleanup"
REPORT_KEY: Final = "pam_report"

MAX_SANDBOX_COMMANDS: Final = 60
CHECK_TIMEOUT_S: Final = 900.0
INSTALL_TIMEOUT_S: Final = 900.0
MAX_FIELD_CHARS: Final = 4000
MAX_OUTPUT_CHARS: Final = 8000
MAX_DIFF_CHARS: Final = 60_000
_JUSTFILE_NAMES: Final = ("justfile", "Justfile")
_MAKEFILE_NAMES: Final = ("Makefile", "makefile")
_LOCKFILE_FOR: Final = {
    "npm": "package-lock.json",
    "pnpm": "pnpm-lock.yaml",
    "yarn": "yarn.lock",
}
_PACKAGE_TOOLS: Final = frozenset({"npm", "pnpm", "yarn", "npx"})
_DRY_RUN_ACTIONS: Final = frozenset({"add", "remove"})


class PamError(Exception):
    """A refusal the model can read and correct. It never ends the run."""


@dataclass(frozen=True)
class _CheckPlan:
    install: list[str] | None
    commands: list[list[str]]


class ImplementerSession:
    """One implementation run: one sandbox, one branch, at most one change request."""

    def __init__(
        self,
        *,
        provider: VcsProvider,
        project: str,
        config: ImplementerConfig,
        sandbox_factory: Callable[[], Sandbox],
        report: dict[str, Any],
    ) -> None:
        self._provider = provider
        self._project = project
        self._config = config
        self._factory = sandbox_factory
        self._report = report
        self._workspace: MonitoredSandbox | None = None
        self._tokens: list[str] = []
        self._base: str | None = None
        self._branch: str | None = None
        self._task_key: str = ""
        self._lockfiles: tuple[str, ...] | None = None
        self._checks: dict[str, CheckOutcome] = {}
        self._tails: dict[str, str] = {}
        self._installed = False
        self._files: set[str] = set()
        self._protected: set[str] = set()
        self._commits = 0
        self._pushed = False
        self._change_request: ChangeRequest | None = None
        self._closed = False
        self.halted: str | None = None

    @property
    def change_request(self) -> ChangeRequest | None:
        return self._change_request

    @property
    def branch(self) -> str | None:
        return self._branch

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._tokens.clear()
        if self._workspace is not None:
            self._workspace.destroy()

    def halt(self, reason: str) -> None:
        self.halted = reason
        self._report["halt"] = reason

    def start(self, task_key: str, summary: str) -> str:
        if self._branch is not None:
            raise PamError(f"work already started on {self._branch}")
        check_task_key(task_key)
        base = self._provider.get_default_branch(self._project)
        branch = branch_name(self._config.branch_template, task_key, summary)
        self._refuse_protected(branch, base)
        workspace = self._open_workspace()
        url = self._provider.clone_url(self._project)
        workspace.clone(url, base, self._credentials(url))
        switched = workspace.exec(["git", "switch", "-c", branch])
        if switched.exit_code != 0:
            raise PamError(f"could not create branch {branch}: {_tail(switched)}")
        self._task_key = task_key
        self._base = base
        self._branch = branch
        self._publish()
        return f"created branch {branch} from {base} in the sandbox"

    def write_file(self, path: str, content: str) -> str:
        self._live().write(path, content)
        return f"wrote {path} ({len(content.encode('utf-8'))} bytes)"

    def apply_patch(self, patch: str) -> str:
        result = self._live().apply_patch(patch)
        if result.exit_code != 0:
            raise PamError(f"patch did not apply: {_tail(result)}")
        return "patch applied"

    def read_file(self, path: str) -> str:
        content = self._live().read(path)
        return wrap_untrusted(_clip(content, MAX_DIFF_CHARS), f"sandbox:{path}")

    def list_dir(self, path: str) -> str:
        workspace = self._live()
        _check_dir_path(path)
        target = f"HEAD:{path}/" if path else "HEAD:"
        listing = workspace.exec(["git", "show", target])
        lines = listing.stdout.splitlines()
        if listing.exit_code != 0 or not lines or not lines[0].startswith("tree "):
            raise PamError(f"not a directory: {path or '/'}")
        entries = {line for line in lines[1:] if line.strip()}
        entries.update(self._untracked_under(workspace, path))
        return wrap_untrusted("\n".join(sorted(entries)) or "empty", f"tree:{path}")

    def diff(self) -> str:
        text = self._live().diff()
        return wrap_untrusted(_clip(text, MAX_DIFF_CHARS), "sandbox:diff")

    def run_command(self, argv: Sequence[str]) -> str:
        result = self._live().exec(list(argv))
        status = "timed out" if result.timed_out else f"exit {result.exit_code}"
        text = self._redact(_clip(result.stdout + result.stderr, MAX_OUTPUT_CHARS))
        return f"{' '.join(result.argv)}: {status}\n" + wrap_untrusted(
            text, f"command:{result.argv[0]}"
        )

    def run_checks(self) -> str:
        workspace = self._live()
        plan = self._check_plan()
        outcomes: list[CheckOutcome] = []
        if plan.install is not None and not self._installed:
            install = self._run_step(workspace, plan.install, INSTALL_TIMEOUT_S)
            outcomes.append(install)
            self._installed = install.passed
        for argv in plan.commands:
            outcomes.append(self._run_step(workspace, argv, CHECK_TIMEOUT_S))
        self._publish()
        return self._checks_text(outcomes)

    def commit(self, message: str, scope: TaskScope) -> str:
        workspace = self._live()
        candidates = self._changed_paths(workspace)
        if not candidates:
            return "nothing to commit: the working tree has no changes"
        violations = protected_path_violations(
            candidates, self._config.protected_paths, scope
        )
        if violations:
            raise PamError(
                "commit refused, these protected paths would change: "
                f'{", ".join(violations)}. Pass protected_paths="allow" only when '
                "the task requires them."
            )
        touched = protected_paths_touched(candidates, self._config.protected_paths)
        staged = workspace.exec(["git", "add", "-A"])
        if staged.exit_code != 0:
            raise PamError(f"git add failed: {_tail(staged)}")
        subject = commit_message(
            self._config.commit_template, summary=message, task_key=self._task_key
        )
        done = workspace.exec(["git", "commit", "-q", "-m", subject])
        if done.exit_code != 0:
            raise PamError(f"git commit failed: {_tail(done)}")
        self._commits += 1
        self._files.update(candidates)
        self._protected.update(touched)
        self._publish()
        note = f"; protected paths included: {', '.join(touched)}" if touched else ""
        return f"committed {len(candidates)} path(s): {subject}{note}"

    def push(self) -> str:
        branch = self._require_branch()
        if self._pushed:
            return f"{branch} is already pushed"
        if self._commits == 0:
            raise PamError("nothing is committed yet; call commit first")
        base = self._base or ""
        self._refuse_protected(branch, base)
        url = self._provider.clone_url(self._project)
        self._live().push(branch, self._credentials(url))
        self._pushed = True
        self._publish()
        return f"pushed {branch}"

    def open_change_request(
        self,
        title: str,
        what: str,
        why: str,
        how_tested: str,
        risks: str,
    ) -> str:
        branch = self._require_branch()
        if not self._pushed:
            raise PamError("push_branch must succeed before opening a change request")
        if self._change_request is not None:
            raise PamError(
                f"change request already opened: {self._change_request.web_url}"
            )
        for field in (title, what, why, how_tested, risks):
            _check_field(field)
        body = render_mr_body(
            self._config.mr_body_template,
            what=what,
            why=why,
            how_tested=how_tested,
            risks=risks,
            checks=list(self._checks.values()),
            protected_touched=sorted(self._protected),
        )
        change_request = self._provider.create_change_request(
            self._project,
            source=branch,
            target=self._base or "",
            title=render_title(
                self._config.mr_title_template,
                summary=title,
                task_key=self._task_key,
            ),
            body=body,
            draft=self._config.mr_draft,
            labels=list(self._config.labels),
            reviewers=list(self._config.reviewers),
            assignees=list(self._config.assignees),
        )
        self._change_request = change_request
        self._publish()
        return f"change request opened: {change_request.web_url}"

    # ----- internals ---------------------------------------------------------

    def _live(self) -> MonitoredSandbox:
        if self._workspace is None or self._branch is None:
            raise PamError("call start_work first")
        return self._workspace

    def _require_branch(self) -> str:
        if self._branch is None:
            raise PamError("call start_work first")
        return self._branch

    def _open_workspace(self) -> MonitoredSandbox:
        if self._workspace is None:
            monitor = TrajectoryMonitor(
                max_commands=MAX_SANDBOX_COMMANDS,
                max_wall_clock_s=float(self._config.sandbox.timeout_seconds),
            )
            self._workspace = MonitoredSandbox(self._factory(), monitor)
        return self._workspace

    def _refuse_protected(self, branch: str, base: str) -> None:
        if branch == base or self._provider.is_protected(self._project, branch):
            raise PamError(f"refusing to use protected branch {branch}")
        validate_branch(branch, DEFAULT_PROTECTED_BRANCHES)

    def _credentials(self, url: str) -> GitCredentials | None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return None
        username, token = self._provider.git_credentials(self._project)
        try:
            credentials = GitCredentials(
                username=username, token=token, host=parts.netloc
            )
        except ValueError as exc:
            raise PamError("git credentials for this project are not usable") from exc
        if token not in self._tokens:
            self._tokens.append(token)
        return credentials

    def _changed_paths(self, workspace: MonitoredSandbox) -> list[str]:
        listing = workspace.exec(["git", "add", "--dry-run", "--all"])
        if listing.exit_code != 0:
            raise PamError("cannot list changed paths")
        paths: set[str] = set()
        for line in listing.stdout.splitlines():
            if not line.strip():
                continue
            action, _, rest = line.partition(" ")
            quoted = rest.startswith("'") and rest.endswith("'") and len(rest) >= 2
            if action not in _DRY_RUN_ACTIONS or not quoted:
                raise PamError(
                    "cannot list changed paths safely; simplify the file names"
                )
            paths.add(rest[1:-1])
        return sorted(paths)

    def _check_plan(self) -> _CheckPlan:
        package_json = self._read_optional("package.json")
        justfile = self._read_first(_JUSTFILE_NAMES)
        makefile = self._read_first(_MAKEFILE_NAMES)
        has_just = justfile is not None and declares_recipe(
            justfile, "check", make=False
        )
        has_make = makefile is not None and declares_recipe(
            makefile, "check", make=True
        )
        names = self._lockfile_names()
        manager = detect_package_manager(names)
        commands = detect_checks(
            package_json,
            has_just,
            has_make,
            self._config.check_commands,
            package_manager=manager,
        )
        needs_packages = any(argv[0] in _PACKAGE_TOOLS for argv in commands)
        install = None
        if needs_packages:
            locked = _LOCKFILE_FOR[manager] in names
            install = install_command(manager, locked=locked)
        return _CheckPlan(install=install, commands=commands)

    def _read_optional(self, path: str) -> str | None:
        try:
            return self._live().read(path)
        except (LoopDetectedError, BudgetExceededError):
            raise
        except SandboxError:
            return None

    def _read_first(self, names: Sequence[str]) -> str | None:
        for name in names:
            text = self._read_optional(name)
            if text is not None:
                return text
        return None

    def _lockfile_names(self) -> tuple[str, ...]:
        if self._lockfiles is None:
            found: list[str] = []
            base = self._base or ""
            for name in _LOCKFILE_FOR.values():
                try:
                    self._provider.read_file(self._project, name, base)
                except NotFoundError:
                    continue
                found.append(name)
            self._lockfiles = tuple(found)
        return self._lockfiles

    def _run_step(
        self, workspace: MonitoredSandbox, argv: list[str], timeout_s: float
    ) -> CheckOutcome:
        result = workspace.exec(argv, timeout_s=timeout_s)
        name = " ".join(argv)
        outcome = CheckOutcome(
            name=name,
            passed=result.exit_code == 0 and not result.timed_out,
            exit_code=result.exit_code,
        )
        self._checks[name] = outcome
        self._tails[name] = self._redact(_clip(result.stdout + result.stderr, 1500))
        return outcome

    def _checks_text(self, outcomes: Sequence[CheckOutcome]) -> str:
        if not outcomes:
            return (
                "No checks were detected. Ask for implementer.check_commands or add a "
                "check recipe to the repository."
            )
        passed = sum(1 for item in outcomes if item.passed)
        lines = [f"{passed}/{len(outcomes)} steps passed"]
        for item in outcomes:
            label = "PASS" if item.passed else "FAIL"
            lines.append(f"{label} {item.name} (exit {item.exit_code})")
            if not item.passed:
                lines.append(
                    wrap_untrusted(self._tails.get(item.name, ""), f"check:{item.name}")
                )
        return "\n".join(lines)

    def _untracked_under(self, workspace: MonitoredSandbox, path: str) -> list[str]:
        status = workspace.exec(
            ["git", "status", "--porcelain", "--untracked-files=all"]
        )
        prefix = f"{path.rstrip('/')}/" if path else ""
        entries: list[str] = []
        for line in status.stdout.splitlines():
            if not line.startswith("?? "):
                continue
            rel = line[3:]
            if rel.startswith(prefix):
                entries.append(rel[len(prefix) :].split("/", 1)[0])
        return sorted(set(entries))

    def _redact(self, text: str) -> str:
        return redact_secrets(text, self._tokens)

    def _publish(self) -> None:
        change_request = self._change_request
        self._report.update(
            {
                "branch": self._branch,
                "mr_url": change_request.web_url if change_request else None,
                "checks": [item.as_dict() for item in self._checks.values()],
                "files_changed": sorted(self._files),
                "protected_paths_touched": sorted(self._protected),
            }
        )


def _tail(result: ExecResult) -> str:
    return _clip(result.stderr or result.stdout, 500)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = limit // 2
    tail_start = len(text) - (limit - head)
    dropped = tail_start - head
    tail = text[tail_start:]
    return f"{text[:head]}\n[... {dropped} characters truncated ...]\n{tail}"


def _check_field(value: str) -> None:
    if len(value) > MAX_FIELD_CHARS:
        raise PamError(f"text fields are limited to {MAX_FIELD_CHARS} characters")


def _check_dir_path(path: str) -> None:
    if not path:
        return
    try:
        check_relpath(path, allow_git=True)
    except SandboxError as exc:
        raise PamError(str(exc)) from exc
    if path.startswith("-"):
        raise PamError("path must not start with '-'")
