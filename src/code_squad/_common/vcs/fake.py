from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from code_squad._common.vcs.base import (
    BotIdentity,
    Capability,
    CapabilityError,
    ChangeRequest,
    ChangeRequestRef,
    CiJob,
    CiRun,
    Comment,
    DiffRefs,
    FileDiff,
    InlineComment,
    Issue,
    NotFoundError,
    RateLimit,
    ReviewEvent,
    StaleHeadError,
    StatusState,
)
from code_squad._common.vcs.diff import parse_patch

ALL_CAPABILITIES: frozenset[Capability] = frozenset(Capability)
FAKE_TOKEN: str = "fake-token-for-tests"


class FakeVcsProvider:
    """In-memory provider. Records every write in ``writes`` for assertions."""

    capabilities: frozenset[Capability]

    def __init__(
        self,
        *,
        name: str = "fake",
        capabilities: frozenset[Capability] = ALL_CAPABILITIES,
        identity: BotIdentity | None = None,
    ) -> None:
        self.name = name
        self.capabilities = capabilities
        self._identity = identity or BotIdentity(username="code-squad-bot", id=1)
        self._crs: dict[ChangeRequestRef, ChangeRequest] = {}
        self._diffs: dict[ChangeRequestRef, tuple[FileDiff, ...]] = {}
        self._files: dict[str, dict[str, str]] = {}
        self._comments: dict[ChangeRequestRef, list[Comment]] = {}
        self._runs: dict[str, list[CiRun]] = {}
        self._jobs: dict[tuple[str, str], list[CiJob]] = {}
        self._logs: dict[tuple[str, str], str] = {}
        self._branches: dict[str, dict[str, str]] = {}
        self._protected: dict[str, set[str]] = {}
        self._default_branch: dict[str, str] = {}
        self._issues: dict[tuple[str, int], Issue] = {}
        self._resolved: set[str] = set()
        self._rate: RateLimit | None = RateLimit(5000, 4999, 0)
        self._next_id = 1000
        self.writes: list[tuple[str, dict[str, Any]]] = []

    # ----- seeding helpers -------------------------------------------------

    def add_change_request(
        self,
        cr: ChangeRequest,
        files: Mapping[str, str],
        file_contents: Mapping[str, str] | None = None,
        extra_diffs: Sequence[FileDiff] = (),
    ) -> None:
        diffs = [_diff(path, patch) for path, patch in files.items()]
        self._crs[cr.ref] = cr
        self._diffs[cr.ref] = tuple(diffs) + tuple(extra_diffs)
        self._comments.setdefault(cr.ref, [])
        self._files.setdefault(cr.ref.project, {}).update(file_contents or {})

    def set_head(self, ref: ChangeRequestRef, sha: str) -> None:
        self._crs[ref] = replace(self._crs[ref], head_sha=sha)

    def seed_comment(self, ref: ChangeRequestRef, comment: Comment) -> None:
        self._comments.setdefault(ref, []).append(comment)

    def add_ci_run(
        self,
        project: str,
        run: CiRun,
        jobs: Sequence[CiJob] = (),
        logs: Mapping[str, str] | None = None,
    ) -> None:
        self._runs.setdefault(project, []).append(run)
        self._jobs[(project, run.id)] = list(jobs)
        for job in jobs:
            self._logs[(project, job.id)] = (logs or {}).get(job.id, "")

    def add_issue(self, issue: Issue) -> None:
        self._issues[(issue.project, issue.number)] = issue

    def set_files(self, project: str, files: Mapping[str, str]) -> None:
        self._files.setdefault(project, {}).update(files)

    def protect(self, project: str, branch: str) -> None:
        self._protected.setdefault(project, set()).add(branch)

    def set_default_branch(self, project: str, branch: str) -> None:
        self._default_branch[project] = branch

    def set_rate_limit(self, rate: RateLimit | None) -> None:
        self._rate = rate

    # ----- protocol ----------------------------------------------------------

    def whoami(self) -> BotIdentity:
        return self._identity

    def get_change_request(self, ref: ChangeRequestRef) -> ChangeRequest:
        return self._cr(ref)

    def get_diff_refs(self, ref: ChangeRequestRef) -> DiffRefs:
        cr = self._cr(ref)
        return DiffRefs(
            base_sha=cr.base_sha, start_sha=cr.base_sha, head_sha=cr.head_sha
        )

    def get_diff(self, ref: ChangeRequestRef, head_sha: str) -> tuple[FileDiff, ...]:
        self._assert_head(ref, head_sha)
        return self._diffs[ref]

    def list_changed_files(self, ref: ChangeRequestRef) -> list[str]:
        return [diff.path for diff in self._diffs.get(ref, ())]

    def read_file(self, project: str, path: str, ref: str) -> str:
        files = self._files.get(project, {})
        if path not in files:
            raise NotFoundError(f"file not found: {path}")
        return files[path]

    def list_tree(self, project: str, path: str, ref: str) -> list[str]:
        prefix = f"{path.rstrip('/')}/" if path else ""
        children: set[str] = set()
        for key in self._files.get(project, {}):
            if key.startswith(prefix):
                children.add(prefix + key[len(prefix) :].split("/", 1)[0])
        return sorted(children)

    def search_repo(
        self, project: str, pattern: str, ref: str
    ) -> list[tuple[str, int, str]]:
        hits: list[tuple[str, int, str]] = []
        for path, text in sorted(self._files.get(project, {}).items()):
            for number, line in enumerate(text.splitlines(), start=1):
                if pattern in line:
                    hits.append((path, number, line.strip()))
                    break
        return hits

    def list_comments(self, ref: ChangeRequestRef) -> list[Comment]:
        return list(self._comments.get(ref, []))

    def post_inline_comments(
        self,
        ref: ChangeRequestRef,
        head_sha: str,
        comments: Sequence[InlineComment],
        diff_refs: DiffRefs,
    ) -> list[str]:
        self._assert_head(ref, head_sha)
        ids: list[str] = []
        for item in comments:
            new_id = self._id()
            self._comments.setdefault(ref, []).append(
                Comment(
                    id=new_id,
                    author=self._identity.username,
                    body=item.body,
                    path=item.path,
                    line=item.line,
                    thread_id=new_id,
                    resolved=False,
                )
            )
            ids.append(new_id)
        self._write(
            "post_inline_comments", ref=ref, count=len(comments), head_sha=head_sha
        )
        return ids

    def post_summary(self, ref: ChangeRequestRef, body: str) -> str:
        new_id = self._id()
        self._comments.setdefault(ref, []).append(
            Comment(new_id, self._identity.username, body, None, None, None, False)
        )
        self._write("post_summary", ref=ref)
        return new_id

    def upsert_comment(self, ref: ChangeRequestRef, marker: str, body: str) -> str:
        comments = self._comments.setdefault(ref, [])
        for index, existing in enumerate(comments):
            if marker in existing.body:
                comments[index] = replace(existing, body=body)
                self._write("upsert_comment", ref=ref, action="update", id=existing.id)
                return existing.id
        new_id = self._id()
        comments.append(
            Comment(new_id, self._identity.username, body, None, None, None, False)
        )
        self._write("upsert_comment", ref=ref, action="create", id=new_id)
        return new_id

    def resolve_thread(self, ref: ChangeRequestRef, thread_id: str) -> None:
        if Capability.RESOLVE_THREAD not in self.capabilities:
            raise CapabilityError("resolve_thread is not supported by this provider")
        self._resolved.add(thread_id)
        self._write("resolve_thread", ref=ref, thread_id=thread_id)

    def set_status(
        self,
        project: str,
        sha: str,
        state: StatusState,
        context: str,
        description: str,
        url: str,
    ) -> str:
        new_id = self._id()
        kind = (
            "check_run"
            if Capability.CHECK_RUNS in self.capabilities
            else "commit_status"
        )
        self._write(
            "set_status",
            project=project,
            sha=sha,
            state=state.value,
            context=context,
            description=description,
            backend=kind,
        )
        return new_id

    def submit_review_verdict(
        self,
        ref: ChangeRequestRef,
        head_sha: str,
        event: ReviewEvent,
        body: str,
    ) -> str:
        self._assert_head(ref, head_sha)
        self._write("submit_review_verdict", ref=ref, event=event, body=body)
        return self._id()

    def list_ci_runs(self, project: str, ref: str) -> list[CiRun]:
        return [run for run in self._runs.get(project, []) if ref in (run.sha, run.ref)]

    def list_ci_jobs(self, project: str, run_id: str) -> list[CiJob]:
        return list(self._jobs.get((project, run_id), []))

    def get_job_log(self, project: str, job_id: str, max_bytes: int) -> str:
        raw = self._logs.get((project, job_id), "").encode("utf-8")
        return (
            raw[-max_bytes:].decode("utf-8", errors="replace") if max_bytes > 0 else ""
        )

    def create_branch(self, project: str, name: str, from_sha: str) -> str:
        self._branches.setdefault(project, {})[name] = from_sha
        self._write("create_branch", project=project, name=name, from_sha=from_sha)
        return name

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
    ) -> ChangeRequest:
        number = 1 + max(
            (ref.number for ref in self._crs if ref.project == project), default=0
        )
        ref = ChangeRequestRef(project, number)
        head = self._branches.get(project, {}).get(source, "0" * 40)
        cr = ChangeRequest(
            ref=ref,
            title=title,
            description=body,
            author=self._identity.username,
            source_branch=source,
            target_branch=target,
            head_sha=head,
            base_sha="0" * 40,
            draft=draft,
            is_fork=False,
            web_url=f"https://fake.invalid/{project}/-/merge_requests/{number}",
            labels=tuple(labels),
            state="opened",
        )
        self._crs[ref] = cr
        self._diffs[ref] = ()
        self._write("create_change_request", project=project, draft=draft, title=title)
        return cr

    def add_labels(self, ref: ChangeRequestRef, labels: Sequence[str]) -> None:
        cr = self._cr(ref)
        self._crs[ref] = replace(cr, labels=tuple(dict.fromkeys([*cr.labels, *labels])))
        self._write("add_labels", ref=ref, labels=list(labels))

    def request_reviewers(
        self, ref: ChangeRequestRef, reviewers: Sequence[str]
    ) -> None:
        self._cr(ref)
        self._write("request_reviewers", ref=ref, reviewers=list(reviewers))

    def get_default_branch(self, project: str) -> str:
        return self._default_branch.get(project, "main")

    def is_protected(self, project: str, branch: str) -> bool:
        return branch in self._protected.get(project, set())

    def get_issue(self, project: str, number: int) -> Issue:
        issue = self._issues.get((project, number))
        if issue is None:
            raise NotFoundError(f"issue {number} not found")
        return issue

    def comment_on_issue(self, project: str, number: int, body: str) -> str:
        self.get_issue(project, number)
        self._write("comment_on_issue", project=project, number=number, body=body)
        return self._id()

    def rate_limit(self) -> RateLimit | None:
        return self._rate

    def clone_url(self, project: str) -> str:
        return f"https://fake.invalid/{project}.git"

    def git_credentials(self, project: str) -> tuple[str, str]:
        return ("fake-user", FAKE_TOKEN)

    # ----- internals -------------------------------------------------------

    def _cr(self, ref: ChangeRequestRef) -> ChangeRequest:
        cr = self._crs.get(ref)
        if cr is None:
            raise NotFoundError(f"change request {ref.number} not found")
        return cr

    def _assert_head(self, ref: ChangeRequestRef, head_sha: str) -> None:
        current = self._cr(ref).head_sha
        if current != head_sha:
            raise StaleHeadError(f"change request head moved to {current[:12]}")

    def _id(self) -> str:
        self._next_id += 1
        return str(self._next_id)

    def _write(self, kind: str, **data: Any) -> None:
        self.writes.append((kind, dict(data)))


def _diff(path: str, patch: str) -> FileDiff:
    return FileDiff(
        path=path,
        old_path=path,
        status="modified",
        hunks=parse_patch(patch),
        patch=patch,
        binary=False,
        truncated=False,
    )
