from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Final
from urllib.parse import quote

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
    FileStatus,
    InlineComment,
    Issue,
    NotFoundError,
    RateLimit,
    ReviewEvent,
    StaleHeadError,
    StatusState,
    VcsError,
)
from code_squad._common.vcs.diff import parse_patch
from code_squad._common.vcs.http import HttpClient, as_dict, as_list, tail_text

_SHA: Final = re.compile(r"^[0-9a-f]{40}$")
_CAPABILITIES: Final = frozenset(
    {
        Capability.COMMIT_STATUS,
        Capability.APPROVE,
        Capability.DRAFT_CHANGE_REQUEST,
        Capability.RESOLVE_THREAD,
        Capability.CI_LOGS,
        Capability.ISSUES,
        Capability.PUSH,
    }
)
_STATE: Final[dict[StatusState, str]] = {
    StatusState.PENDING: "pending",
    StatusState.SUCCESS: "success",
    StatusState.FAILED: "failed",
    StatusState.ERROR: "failed",
}
_SEARCH_UNAVAILABLE: Final = (401, 403, 404)


class GitLabProvider:
    name: str = "gitlab"
    capabilities: frozenset[Capability] = _CAPABILITIES

    def __init__(
        self, base_url: str, token: str, http: HttpClient | None = None
    ) -> None:
        self._root = base_url.rstrip("/")
        self._api = f"{self._root}/api/v4"
        self._token = token
        self._http = http or HttpClient(provider="gitlab")

    def whoami(self) -> BotIdentity:
        data = as_dict(self._get(f"{self._api}/user"))
        return BotIdentity(username=str(data["username"]), id=int(data["id"]))

    def get_change_request(self, ref: ChangeRequestRef) -> ChangeRequest:
        return _to_cr(ref, self._mr(ref))

    def get_diff_refs(self, ref: ChangeRequestRef) -> DiffRefs:
        refs = as_dict(self._mr(ref).get("diff_refs") or {})
        return DiffRefs(
            base_sha=str(refs["base_sha"]),
            start_sha=str(refs["start_sha"]),
            head_sha=str(refs["head_sha"]),
        )

    def get_diff(self, ref: ChangeRequestRef, head_sha: str) -> tuple[FileDiff, ...]:
        self._assert_head(ref, head_sha)
        items = self._list(self._mr_url(ref, "/diffs"))
        return tuple(_file_diff(as_dict(item)) for item in items)

    def list_changed_files(self, ref: ChangeRequestRef) -> list[str]:
        items = self._list(self._mr_url(ref, "/diffs"))
        return [_path_of(as_dict(item)) for item in items]

    def read_file(self, project: str, path: str, ref: str) -> str:
        url = self._proj_url(project, f"/repository/files/{quote(path, safe='')}/raw")
        response = self._http.request(
            "GET", url, headers=self._headers(), params={"ref": ref}
        )
        return response.text

    def list_tree(self, project: str, path: str, ref: str) -> list[str]:
        url = self._proj_url(project, "/repository/tree")
        items = self._list(url, {"path": path, "ref": ref})
        return [str(as_dict(item)["path"]) for item in items]

    def search_repo(
        self, project: str, pattern: str, ref: str
    ) -> list[tuple[str, int, str]]:
        url = self._proj_url(project, "/search")
        try:
            items = self._list(url, {"scope": "blobs", "search": pattern, "ref": ref})
        except VcsError as exc:
            if exc.status_code in _SEARCH_UNAVAILABLE:
                raise CapabilityError(
                    "code search is unavailable on this GitLab"
                ) from exc
            raise
        return [_search_hit(as_dict(item)) for item in items]

    def list_comments(self, ref: ChangeRequestRef) -> list[Comment]:
        discussions = self._list(self._mr_url(ref, "/discussions"))
        comments: list[Comment] = []
        for raw in discussions:
            discussion = as_dict(raw)
            for raw_note in as_list(discussion.get("notes") or []):
                note = as_dict(raw_note)
                if not note.get("system"):
                    comments.append(_comment(str(discussion["id"]), note))
        return comments

    def post_inline_comments(
        self,
        ref: ChangeRequestRef,
        head_sha: str,
        comments: Sequence[InlineComment],
        diff_refs: DiffRefs,
    ) -> list[str]:
        if not comments:
            return []
        self._assert_head(ref, head_sha)
        ids: list[str] = []
        for comment in comments:
            body = {"body": comment.body, "position": _position(comment, diff_refs)}
            data = as_dict(self._post(self._mr_url(ref, "/discussions"), body))
            ids.append(str(data["id"]))
        return ids

    def post_summary(self, ref: ChangeRequestRef, body: str) -> str:
        data = as_dict(self._post(self._mr_url(ref, "/notes"), {"body": body}))
        return str(data["id"])

    def upsert_comment(self, ref: ChangeRequestRef, marker: str, body: str) -> str:
        existing = self._find_note(ref, marker)
        if existing is None:
            return self.post_summary(ref, body)
        url = self._mr_url(ref, f"/notes/{existing}")
        data = as_dict(self._put(url, {"body": body}))
        return str(data["id"])

    def resolve_thread(self, ref: ChangeRequestRef, thread_id: str) -> None:
        url = self._mr_url(ref, f"/discussions/{thread_id}")
        self._put(url, {"resolved": True})

    def set_status(
        self,
        project: str,
        sha: str,
        state: StatusState,
        context: str,
        description: str,
        url: str,
    ) -> str:
        body: dict[str, str] = {
            "state": _STATE[state],
            "name": context,
            "description": description,
        }
        if url:
            body["target_url"] = url
        data = as_dict(self._post(self._proj_url(project, f"/statuses/{sha}"), body))
        return str(data["id"])

    def submit_review_verdict(
        self,
        ref: ChangeRequestRef,
        head_sha: str,
        event: ReviewEvent,
        body: str,
    ) -> str:
        if event == "APPROVE":
            self._assert_head(ref, head_sha)
            self._post(self._mr_url(ref, "/approve"), {"sha": head_sha})
            return "approved"
        return self.post_summary(ref, body)

    def list_ci_runs(self, project: str, ref: str) -> list[CiRun]:
        key = "sha" if _SHA.match(ref) else "ref"
        items = self._list(self._proj_url(project, "/pipelines"), {key: ref})
        return [_run(as_dict(item)) for item in items]

    def list_ci_jobs(self, project: str, run_id: str) -> list[CiJob]:
        items = self._list(self._proj_url(project, f"/pipelines/{run_id}/jobs"))
        return [_job(as_dict(item)) for item in items]

    def get_job_log(self, project: str, job_id: str, max_bytes: int) -> str:
        url = self._proj_url(project, f"/jobs/{job_id}/trace")
        response = self._http.request("GET", url, headers=self._headers())
        return tail_text(response.content, max_bytes)

    def create_branch(self, project: str, name: str, from_sha: str) -> str:
        url = self._proj_url(project, "/repository/branches")
        self._post(url, {"branch": name, "ref": from_sha})
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
        payload: dict[str, Any] = {
            "source_branch": source,
            "target_branch": target,
            "title": f"Draft: {title}" if draft else title,
            "description": body,
            "labels": ",".join(labels),
            "reviewer_ids": [self._user_id(name) for name in reviewers],
            "assignee_ids": [self._user_id(name) for name in assignees],
        }
        data = as_dict(self._post(self._proj_url(project, "/merge_requests"), payload))
        return _to_cr(ChangeRequestRef(project, int(data["iid"])), data)

    def add_labels(self, ref: ChangeRequestRef, labels: Sequence[str]) -> None:
        self._put(self._mr_url(ref), {"add_labels": ",".join(labels)})

    def request_reviewers(
        self, ref: ChangeRequestRef, reviewers: Sequence[str]
    ) -> None:
        current = [
            int(as_dict(r)["id"]) for r in as_list(self._mr(ref).get("reviewers") or [])
        ]
        added = [self._user_id(name) for name in reviewers]
        merged = list(dict.fromkeys([*current, *added]))
        self._put(self._mr_url(ref), {"reviewer_ids": merged})

    def get_default_branch(self, project: str) -> str:
        data = as_dict(self._get(self._proj_url(project, "")))
        return str(data["default_branch"])

    def is_protected(self, project: str, branch: str) -> bool:
        url = self._proj_url(project, f"/protected_branches/{quote(branch, safe='')}")
        try:
            self._get(url)
        except NotFoundError:
            return False
        return True

    def get_issue(self, project: str, number: int) -> Issue:
        data = as_dict(self._get(self._proj_url(project, f"/issues/{number}")))
        return Issue(
            project=project,
            number=number,
            title=str(data.get("title") or ""),
            body=str(data.get("description") or ""),
            labels=tuple(str(label) for label in as_list(data.get("labels") or [])),
            assignees=tuple(
                str(as_dict(a).get("username", ""))
                for a in as_list(data.get("assignees") or [])
            ),
            state=_issue_state(str(data.get("state", ""))),
            web_url=str(data.get("web_url") or ""),
        )

    def comment_on_issue(self, project: str, number: int, body: str) -> str:
        url = self._proj_url(project, f"/issues/{number}/notes")
        return str(as_dict(self._post(url, {"body": body}))["id"])

    def rate_limit(self) -> RateLimit | None:
        return None

    def clone_url(self, project: str) -> str:
        return f"{self._root}/{project}.git"

    def git_credentials(self, project: str) -> tuple[str, str]:
        return ("oauth2", self._token)

    def _headers(self) -> dict[str, str]:
        return {"PRIVATE-TOKEN": self._token}

    def _proj_url(self, project: str, suffix: str) -> str:
        return f"{self._api}/projects/{quote(project, safe='')}{suffix}"

    def _mr_url(self, ref: ChangeRequestRef, suffix: str = "") -> str:
        return self._proj_url(ref.project, f"/merge_requests/{ref.number}{suffix}")

    def _mr(self, ref: ChangeRequestRef) -> dict[str, Any]:
        return as_dict(self._get(self._mr_url(ref)))

    def _assert_head(self, ref: ChangeRequestRef, head_sha: str) -> None:
        current = str(self._mr(ref)["sha"])
        if current != head_sha:
            raise StaleHeadError(f"change request head moved to {current[:12]}")

    def _find_note(self, ref: ChangeRequestRef, marker: str) -> str | None:
        for raw in self._list(self._mr_url(ref, "/notes")):
            note = as_dict(raw)
            if not note.get("system") and marker in str(note.get("body") or ""):
                return str(note["id"])
        return None

    def _user_id(self, username: str) -> int:
        users = self._list(f"{self._api}/users", {"username": username})
        if not users:
            raise NotFoundError("user not found on GitLab")
        return int(as_dict(users[0])["id"])

    def _get(self, url: str) -> Any:
        return self._http.get_json(url, headers=self._headers())

    def _list(self, url: str, params: dict[str, Any] | None = None) -> list[Any]:
        query: dict[str, Any] = {"per_page": 100, **(params or {})}
        return self._http.get_list(url, headers=self._headers(), params=query)

    def _post(self, url: str, body: dict[str, Any]) -> Any:
        return self._http.request(
            "POST", url, headers=self._headers(), json=body
        ).json()

    def _put(self, url: str, body: dict[str, Any]) -> Any:
        return self._http.request("PUT", url, headers=self._headers(), json=body).json()


def _to_cr(ref: ChangeRequestRef, data: dict[str, Any]) -> ChangeRequest:
    refs = as_dict(data.get("diff_refs") or {})
    author = as_dict(data.get("author") or {})
    return ChangeRequest(
        ref=ref,
        title=str(data.get("title") or ""),
        description=str(data.get("description") or ""),
        author=str(author.get("username") or ""),
        source_branch=str(data["source_branch"]),
        target_branch=str(data["target_branch"]),
        head_sha=str(data.get("sha") or refs.get("head_sha") or ""),
        base_sha=str(refs.get("base_sha") or ""),
        draft=bool(data.get("draft") or data.get("work_in_progress")),
        is_fork=data.get("source_project_id") != data.get("target_project_id"),
        web_url=str(data.get("web_url") or ""),
        labels=tuple(str(label) for label in as_list(data.get("labels") or [])),
        state=str(data.get("state") or ""),
    )


def _file_diff(item: dict[str, Any]) -> FileDiff:
    too_large = bool(item.get("too_large"))
    patch = "" if too_large else str(item.get("diff") or "")
    new_path = str(item.get("new_path") or item.get("old_path") or "")
    return FileDiff(
        path=new_path,
        old_path=str(item.get("old_path") or new_path),
        status=_status(item),
        hunks=parse_patch(patch),
        patch=patch,
        binary=bool(item.get("binary")),
        truncated=too_large,
    )


def _status(item: dict[str, Any]) -> FileStatus:
    if item.get("new_file"):
        return "added"
    if item.get("deleted_file"):
        return "deleted"
    if item.get("renamed_file"):
        return "renamed"
    return "modified"


def _path_of(item: dict[str, Any]) -> str:
    return str(item.get("new_path") or item.get("old_path") or "")


def _search_hit(item: dict[str, Any]) -> tuple[str, int, str]:
    first_line = str(item.get("data") or "").split("\n", 1)[0].strip()
    return (str(item["path"]), int(item["startline"]), first_line)


def _comment(thread: str, note: dict[str, Any]) -> Comment:
    position = as_dict(note.get("position") or {})
    line = position.get("new_line")
    return Comment(
        id=str(note["id"]),
        author=str(as_dict(note.get("author") or {}).get("username") or ""),
        body=str(note.get("body") or ""),
        path=_opt_str(position.get("new_path")),
        line=int(line) if line is not None else None,
        thread_id=thread,
        resolved=bool(note.get("resolved")),
    )


def _position(comment: InlineComment, refs: DiffRefs) -> dict[str, Any]:
    position: dict[str, Any] = {
        "position_type": "text",
        "base_sha": refs.base_sha,
        "start_sha": refs.start_sha,
        "head_sha": refs.head_sha,
        "old_path": comment.path,
        "new_path": comment.path,
    }
    if comment.side == "RIGHT":
        position["new_line"] = comment.line
    else:
        position["old_line"] = comment.line
    return position


def _run(data: dict[str, Any]) -> CiRun:
    return CiRun(
        id=str(data["id"]),
        status=str(data.get("status") or ""),
        ref=str(data.get("ref") or ""),
        sha=str(data.get("sha") or ""),
        web_url=str(data.get("web_url") or ""),
        name=str(data.get("name") or "pipeline"),
    )


def _job(data: dict[str, Any]) -> CiJob:
    return CiJob(
        id=str(data["id"]),
        name=str(data.get("name") or ""),
        status=str(data.get("status") or ""),
        stage=str(data.get("stage") or ""),
        web_url=str(data.get("web_url") or ""),
    )


def _issue_state(state: str) -> str:
    return "open" if state == "opened" else state


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)
