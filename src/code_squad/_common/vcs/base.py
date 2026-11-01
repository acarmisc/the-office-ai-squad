from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol

FileStatus = Literal["added", "modified", "deleted", "renamed"]
ReviewEvent = Literal["COMMENT", "REQUEST_CHANGES", "APPROVE"]
ApproveMode = Literal["none", "comment", "approve"]


class StatusState(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    ERROR = "error"


class Capability(StrEnum):
    CHECK_RUNS = "check_runs"
    COMMIT_STATUS = "commit_status"
    BATCHED_REVIEW = "batched_review"
    APPROVE = "approve"
    DRAFT_CHANGE_REQUEST = "draft_change_request"
    RESOLVE_THREAD = "resolve_thread"
    CI_LOGS = "ci_logs"
    ISSUES = "issues"
    PUSH = "push"


class VcsError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CapabilityError(VcsError):
    pass


class NotFoundError(VcsError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404)


class RateLimitedError(VcsError):
    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.retry_after = retry_after


class StaleHeadError(VcsError):
    pass


class ProtectedBranchError(VcsError):
    pass


@dataclass(frozen=True)
class ChangeRequestRef:
    project: str
    number: int


@dataclass(frozen=True)
class DiffRefs:
    base_sha: str
    start_sha: str
    head_sha: str


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    added_lines: frozenset[int] = field(default_factory=frozenset)

    @property
    def new_end(self) -> int:
        return self.new_start + self.new_lines - 1


@dataclass(frozen=True)
class FileDiff:
    path: str
    old_path: str
    status: FileStatus
    hunks: tuple[Hunk, ...]
    patch: str
    binary: bool
    truncated: bool


@dataclass(frozen=True)
class ChangeRequest:
    ref: ChangeRequestRef
    title: str
    description: str
    author: str
    source_branch: str
    target_branch: str
    head_sha: str
    base_sha: str
    draft: bool
    is_fork: bool
    web_url: str
    labels: tuple[str, ...]
    state: str


@dataclass(frozen=True)
class Comment:
    id: str
    author: str
    body: str
    path: str | None
    line: int | None
    thread_id: str | None
    resolved: bool


@dataclass(frozen=True)
class CiRun:
    id: str
    status: str
    ref: str
    sha: str
    web_url: str
    name: str


@dataclass(frozen=True)
class CiJob:
    id: str
    name: str
    status: str
    stage: str
    web_url: str


@dataclass(frozen=True)
class Issue:
    project: str
    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    assignees: tuple[str, ...]
    state: str
    web_url: str


@dataclass(frozen=True)
class BotIdentity:
    username: str
    id: int


@dataclass(frozen=True)
class RateLimit:
    limit: int
    remaining: int
    reset_epoch: int


@dataclass(frozen=True)
class InlineComment:
    path: str
    line: int
    body: str
    side: Literal["RIGHT", "LEFT"] = "RIGHT"


class VcsProvider(Protocol):
    name: str
    capabilities: frozenset[Capability]

    def whoami(self) -> BotIdentity: ...

    def get_change_request(self, ref: ChangeRequestRef) -> ChangeRequest: ...

    def get_diff_refs(self, ref: ChangeRequestRef) -> DiffRefs: ...

    def get_diff(
        self, ref: ChangeRequestRef, head_sha: str
    ) -> tuple[FileDiff, ...]: ...

    def list_changed_files(self, ref: ChangeRequestRef) -> list[str]: ...

    def read_file(self, project: str, path: str, ref: str) -> str: ...

    def list_tree(self, project: str, path: str, ref: str) -> list[str]: ...

    def search_repo(
        self, project: str, pattern: str, ref: str
    ) -> list[tuple[str, int, str]]: ...

    def list_comments(self, ref: ChangeRequestRef) -> list[Comment]: ...

    def post_inline_comments(
        self,
        ref: ChangeRequestRef,
        head_sha: str,
        comments: Sequence[InlineComment],
        diff_refs: DiffRefs,
    ) -> list[str]: ...

    def post_summary(self, ref: ChangeRequestRef, body: str) -> str: ...

    def upsert_comment(self, ref: ChangeRequestRef, marker: str, body: str) -> str: ...

    def resolve_thread(self, ref: ChangeRequestRef, thread_id: str) -> None: ...

    def set_status(
        self,
        project: str,
        sha: str,
        state: StatusState,
        context: str,
        description: str,
        url: str,
    ) -> str: ...

    def submit_review_verdict(
        self,
        ref: ChangeRequestRef,
        head_sha: str,
        event: ReviewEvent,
        body: str,
    ) -> str: ...

    def list_ci_runs(self, project: str, ref: str) -> list[CiRun]: ...

    def list_ci_jobs(self, project: str, run_id: str) -> list[CiJob]: ...

    def get_job_log(self, project: str, job_id: str, max_bytes: int) -> str: ...

    def create_branch(self, project: str, name: str, from_sha: str) -> str: ...

    def create_change_request(
        self,
        project: str,
        source: str,
        target: str,
        title: str,
        body: str,
        draft: bool,
        labels: Sequence[str],
        reviewers: Sequence[str],
        assignees: Sequence[str],
    ) -> ChangeRequest: ...

    def add_labels(self, ref: ChangeRequestRef, labels: Sequence[str]) -> None: ...

    def request_reviewers(
        self, ref: ChangeRequestRef, reviewers: Sequence[str]
    ) -> None: ...

    def get_default_branch(self, project: str) -> str: ...

    def is_protected(self, project: str, branch: str) -> bool: ...

    def get_issue(self, project: str, number: int) -> Issue: ...

    def comment_on_issue(self, project: str, number: int, body: str) -> str: ...

    def rate_limit(self) -> RateLimit | None: ...

    def clone_url(self, project: str) -> str: ...

    def git_credentials(self, project: str) -> tuple[str, str]: ...
