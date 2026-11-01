from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Final, Literal, Protocol
from urllib.parse import quote, urlsplit

import jwt

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
)
from code_squad._common.vcs.diff import parse_patch
from code_squad._common.vcs.http import HttpClient, as_dict, as_list, tail_text

DEFAULT_BASE_URL: Final = "https://api.github.com"
_API_VERSION: Final = "2022-11-28"
_JSON: Final = "application/vnd.github+json"
_RAW: Final = "application/vnd.github.raw"
_SHA: Final = re.compile(r"^[0-9a-f]{40}$")
_REFRESH_MARGIN_SECONDS: Final = 300.0
_SEARCH_FILES: Final = 10
_BASE_CAPABILITIES: Final = frozenset(
    {
        Capability.BATCHED_REVIEW,
        Capability.APPROVE,
        Capability.DRAFT_CHANGE_REQUEST,
        Capability.CI_LOGS,
        Capability.ISSUES,
        Capability.PUSH,
        Capability.COMMIT_STATUS,
    }
)
_COMMIT_STATE: Final[dict[StatusState, str]] = {
    StatusState.PENDING: "pending",
    StatusState.SUCCESS: "success",
    StatusState.FAILED: "failure",
    StatusState.ERROR: "error",
}
_CONCLUSION: Final[dict[StatusState, str]] = {
    StatusState.SUCCESS: "success",
    StatusState.FAILED: "failure",
    StatusState.ERROR: "failure",
}


class GitHubAuth(Protocol):
    @property
    def kind(self) -> Literal["app", "token"]: ...

    def headers(self, repo: str) -> dict[str, str]: ...

    def identity_headers(self) -> dict[str, str]: ...

    def token_for(self, repo: str) -> str: ...


class TokenAuth:
    kind: Literal["app", "token"] = "token"

    def __init__(self, token: str) -> None:
        self._token = token

    def headers(self, repo: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def identity_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def token_for(self, repo: str) -> str:
        return self._token


class AppAuth:
    kind: Literal["app", "token"] = "app"

    def __init__(
        self,
        app_id: str,
        private_key_pem: str,
        installation_id: int | None = None,
        *,
        http: HttpClient | None = None,
        clock: Callable[[], float] = time.time,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._app_id = app_id
        self._key = private_key_pem
        self._installation_id = installation_id
        self._http = http or HttpClient(provider="github")
        self._clock = clock
        self._base = base_url.rstrip("/")
        self._installations: dict[str, int] = {}
        self._tokens: dict[str, tuple[str, float]] = {}

    def identity_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._app_jwt()}"}

    def headers(self, repo: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token_for(repo)}"}

    def token_for(self, repo: str) -> str:
        cached = self._tokens.get(repo)
        if cached is not None and self._clock() < cached[1] - _REFRESH_MARGIN_SECONDS:
            return cached[0]
        token, expires_at = self._mint(repo)
        self._tokens[repo] = (token, expires_at)
        return token

    def _app_jwt(self) -> str:
        now = int(self._clock())
        claims = {"iat": now - 60, "exp": now + 540, "iss": self._app_id}
        return str(jwt.encode(claims, self._key, algorithm="RS256"))

    def _mint(self, repo: str) -> tuple[str, float]:
        url = f"{self._base}/app/installations/{self._installation(repo)}/access_tokens"
        body = {"repositories": [repo.split("/", 1)[-1]]}
        response = self._http.request(
            "POST",
            url,
            headers={**self.identity_headers(), "Accept": _JSON},
            json=body,
        )
        data = as_dict(response.json())
        expires = datetime.fromisoformat(str(data["expires_at"])).timestamp()
        return str(data["token"]), expires

    def _installation(self, repo: str) -> int:
        if self._installation_id is not None:
            return self._installation_id
        if repo not in self._installations:
            url = f"{self._base}/repos/{repo}/installation"
            data = as_dict(
                self._http.get_json(
                    url, headers={**self.identity_headers(), "Accept": _JSON}
                )
            )
            self._installations[repo] = int(data["id"])
        return self._installations[repo]


class GitHubProvider:
    name: str = "github"
    capabilities: frozenset[Capability]

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        auth: GitHubAuth,
        http: HttpClient | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._auth = auth
        self._http = http or HttpClient(provider="github")
        extra = {Capability.CHECK_RUNS} if auth.kind == "app" else set()
        self.capabilities = _BASE_CAPABILITIES | frozenset(extra)

    @property
    def auth(self) -> GitHubAuth:
        return self._auth

    def whoami(self) -> BotIdentity:
        if self._auth.kind == "app":
            app = as_dict(
                self._http.get_json(f"{self._base}/app", headers=self._ident())
            )
            return BotIdentity(username=f"{app['slug']}[bot]", id=int(app["id"]))
        user = as_dict(self._http.get_json(f"{self._base}/user", headers=self._ident()))
        return BotIdentity(username=str(user["login"]), id=int(user["id"]))

    def get_change_request(self, ref: ChangeRequestRef) -> ChangeRequest:
        return _to_cr(ref.project, self._pull(ref))

    def get_diff_refs(self, ref: ChangeRequestRef) -> DiffRefs:
        pull = self._pull(ref)
        base = as_dict(pull["base"])
        head = as_dict(pull["head"])
        return DiffRefs(
            base_sha=str(base["sha"]),
            start_sha=str(base["sha"]),
            head_sha=str(head["sha"]),
        )

    def get_diff(self, ref: ChangeRequestRef, head_sha: str) -> tuple[FileDiff, ...]:
        self._assert_head(ref, head_sha)
        items = self._list(ref.project, f"/pulls/{ref.number}/files")
        return tuple(_file_diff(as_dict(item)) for item in items)

    def list_changed_files(self, ref: ChangeRequestRef) -> list[str]:
        items = self._list(ref.project, f"/pulls/{ref.number}/files")
        return [str(as_dict(item)["filename"]) for item in items]

    def read_file(self, project: str, path: str, ref: str) -> str:
        url = self._contents_url(project, path)
        response = self._http.request(
            "GET",
            url,
            headers=self._headers(project, _RAW),
            params={"ref": ref},
        )
        return response.text

    def list_tree(self, project: str, path: str, ref: str) -> list[str]:
        items = self._list(project, f"/contents/{quote(path, safe='/')}", {"ref": ref})
        return [str(as_dict(item)["path"]) for item in items]

    def search_repo(
        self, project: str, pattern: str, ref: str
    ) -> list[tuple[str, int, str]]:
        params = {"q": f"{pattern} repo:{project}", "per_page": _SEARCH_FILES}
        data = as_dict(self._get(project, f"{self._base}/search/code", params))
        hits: list[tuple[str, int, str]] = []
        for raw in as_list(data.get("items") or [])[:_SEARCH_FILES]:
            path = str(as_dict(raw)["path"])
            hits.extend(self._first_match(project, path, ref, pattern))
        return hits

    def list_comments(self, ref: ChangeRequestRef) -> list[Comment]:
        issue_items = self._list(ref.project, f"/issues/{ref.number}/comments")
        review_items = self._list(ref.project, f"/pulls/{ref.number}/comments")
        general = [_issue_comment(as_dict(item)) for item in issue_items]
        inline = [_review_comment(as_dict(item)) for item in review_items]
        return general + inline

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
        body = {
            "commit_id": head_sha,
            "event": "COMMENT",
            "body": "",
            "comments": [_review_entry(comment) for comment in comments],
        }
        data = as_dict(self._post(ref.project, _pulls(ref, "/reviews"), body))
        return [str(data["id"])]

    def post_summary(self, ref: ChangeRequestRef, body: str) -> str:
        url = f"/issues/{ref.number}/comments"
        return str(as_dict(self._post(ref.project, url, {"body": body}))["id"])

    def upsert_comment(self, ref: ChangeRequestRef, marker: str, body: str) -> str:
        for raw in self._list(ref.project, f"/issues/{ref.number}/comments"):
            comment = as_dict(raw)
            if marker in str(comment.get("body") or ""):
                url = (
                    f"{self._base}/repos/{ref.project}/issues/comments/{comment['id']}"
                )
                data = as_dict(self._patch(ref.project, url, {"body": body}))
                return str(data["id"])
        return self.post_summary(ref, body)

    def resolve_thread(self, ref: ChangeRequestRef, thread_id: str) -> None:
        if Capability.RESOLVE_THREAD not in self.capabilities:
            raise CapabilityError("resolving review threads needs GraphQL; unsupported")

    def set_status(
        self,
        project: str,
        sha: str,
        state: StatusState,
        context: str,
        description: str,
        url: str,
    ) -> str:
        if Capability.CHECK_RUNS in self.capabilities:
            data = self._check_run(project, sha, state, context, description, url)
        else:
            data = self._commit_status(project, sha, state, context, description, url)
        return str(as_dict(data)["id"])

    def submit_review_verdict(
        self,
        ref: ChangeRequestRef,
        head_sha: str,
        event: ReviewEvent,
        body: str,
    ) -> str:
        self._assert_head(ref, head_sha)
        payload = {"commit_id": head_sha, "event": event, "body": body}
        data = as_dict(self._post(ref.project, _pulls(ref, "/reviews"), payload))
        return str(data["id"])

    def list_ci_runs(self, project: str, ref: str) -> list[CiRun]:
        key = "head_sha" if _SHA.match(ref) else "branch"
        data = as_dict(
            self._get(project, f"{self._base}/repos/{project}/actions/runs", {key: ref})
        )
        return [
            _run(as_dict(item)) for item in as_list(data.get("workflow_runs") or [])
        ]

    def list_ci_jobs(self, project: str, run_id: str) -> list[CiJob]:
        url = f"/actions/runs/{run_id}/jobs"
        items = self._list(project, url, key="jobs")
        return [_job(as_dict(item)) for item in items]

    def get_job_log(self, project: str, job_id: str, max_bytes: int) -> str:
        url = f"{self._base}/repos/{project}/actions/jobs/{job_id}/logs"
        response = self._http.request("GET", url, headers=self._headers(project))
        return tail_text(response.content, max_bytes)

    def create_branch(self, project: str, name: str, from_sha: str) -> str:
        self._post(project, "/git/refs", {"ref": f"refs/heads/{name}", "sha": from_sha})
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
        payload = {
            "title": title,
            "head": source,
            "base": target,
            "body": body,
            "draft": draft,
        }
        created = as_dict(self._post(project, "/pulls", payload))
        ref = ChangeRequestRef(project, int(created["number"]))
        if labels:
            self.add_labels(ref, labels)
        if reviewers:
            self.request_reviewers(ref, reviewers)
        if assignees:
            self._post(
                project,
                f"/issues/{ref.number}/assignees",
                {"assignees": list(assignees)},
            )
        return self.get_change_request(ref)

    def add_labels(self, ref: ChangeRequestRef, labels: Sequence[str]) -> None:
        self._post(
            ref.project, f"/issues/{ref.number}/labels", {"labels": list(labels)}
        )

    def request_reviewers(
        self, ref: ChangeRequestRef, reviewers: Sequence[str]
    ) -> None:
        body = {"reviewers": list(reviewers)}
        self._post(ref.project, _pulls(ref, "/requested_reviewers"), body)

    def get_default_branch(self, project: str) -> str:
        return str(
            as_dict(self._get(project, f"{self._base}/repos/{project}"))[
                "default_branch"
            ]
        )

    def is_protected(self, project: str, branch: str) -> bool:
        url = f"{self._base}/repos/{project}/branches/{quote(branch, safe='')}"
        try:
            data = as_dict(self._http.get_json(url, headers=self._headers(project)))
        except NotFoundError:
            return False
        return bool(data.get("protected"))

    def get_issue(self, project: str, number: int) -> Issue:
        data = as_dict(
            self._get(project, f"{self._base}/repos/{project}/issues/{number}")
        )
        return Issue(
            project=project,
            number=number,
            title=str(data.get("title") or ""),
            body=str(data.get("body") or ""),
            labels=tuple(
                str(as_dict(lab).get("name", ""))
                for lab in as_list(data.get("labels") or [])
            ),
            assignees=tuple(
                str(as_dict(a).get("login", ""))
                for a in as_list(data.get("assignees") or [])
            ),
            state=str(data.get("state") or ""),
            web_url=str(data.get("html_url") or ""),
        )

    def comment_on_issue(self, project: str, number: int, body: str) -> str:
        url = f"/issues/{number}/comments"
        return str(as_dict(self._post(project, url, {"body": body}))["id"])

    def rate_limit(self) -> RateLimit | None:
        data = as_dict(
            self._http.get_json(f"{self._base}/rate_limit", headers=self._ident())
        )
        core = as_dict(as_dict(data["resources"])["core"])
        return RateLimit(
            limit=int(core["limit"]),
            remaining=int(core["remaining"]),
            reset_epoch=int(core["reset"]),
        )

    def clone_url(self, project: str) -> str:
        host = urlsplit(self._base).netloc
        if host == "api.github.com":
            host = "github.com"
        return f"https://{host}/{project}.git"

    def git_credentials(self, project: str) -> tuple[str, str]:
        return ("x-access-token", self._auth.token_for(project))

    def _ident(self) -> dict[str, str]:
        return {
            **self._auth.identity_headers(),
            "Accept": _JSON,
            "X-GitHub-Api-Version": _API_VERSION,
        }

    def _headers(self, repo: str, accept: str = _JSON) -> dict[str, str]:
        return {
            **self._auth.headers(repo),
            "Accept": accept,
            "X-GitHub-Api-Version": _API_VERSION,
        }

    def _contents_url(self, project: str, path: str) -> str:
        return f"{self._base}/repos/{project}/contents/{quote(path, safe='/')}"

    def _get(self, repo: str, url: str, params: dict[str, Any] | None = None) -> Any:
        return self._http.get_json(url, headers=self._headers(repo), params=params)

    def _list(
        self,
        repo: str,
        suffix: str,
        params: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> list[Any]:
        query: dict[str, Any] = {"per_page": 100, **(params or {})}
        url = f"{self._base}/repos/{repo}{suffix}"
        return self._http.get_list(
            url, headers=self._headers(repo), params=query, key=key
        )

    def _post(self, repo: str, suffix: str, body: dict[str, Any]) -> Any:
        url = f"{self._base}/repos/{repo}{suffix}"
        return self._http.request(
            "POST", url, headers=self._headers(repo), json=body
        ).json()

    def _patch(self, repo: str, url: str, body: dict[str, Any]) -> Any:
        return self._http.request(
            "PATCH", url, headers=self._headers(repo), json=body
        ).json()

    def _pull(self, ref: ChangeRequestRef) -> dict[str, Any]:
        return as_dict(
            self._get(
                ref.project, f"{self._base}/repos/{ref.project}/pulls/{ref.number}"
            )
        )

    def _assert_head(self, ref: ChangeRequestRef, head_sha: str) -> None:
        current = str(as_dict(self._pull(ref)["head"])["sha"])
        if current != head_sha:
            raise StaleHeadError(f"change request head moved to {current[:12]}")

    def _first_match(
        self, project: str, path: str, ref: str, pattern: str
    ) -> list[tuple[str, int, str]]:
        text = self.read_file(project, path, ref)
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern in line:
                return [(path, number, line.strip())]
        return []

    def _check_run(
        self,
        project: str,
        sha: str,
        state: StatusState,
        context: str,
        description: str,
        url: str,
    ) -> Any:
        body: dict[str, Any] = {
            "name": context,
            "head_sha": sha,
            "output": {"title": context, "summary": description},
        }
        if url:
            body["details_url"] = url
        if state is StatusState.PENDING:
            body["status"] = "in_progress"
        else:
            body["status"] = "completed"
            body["conclusion"] = _CONCLUSION[state]
        return self._post(project, "/check-runs", body)

    def _commit_status(
        self,
        project: str,
        sha: str,
        state: StatusState,
        context: str,
        description: str,
        url: str,
    ) -> Any:
        body: dict[str, str] = {
            "state": _COMMIT_STATE[state],
            "context": context,
            "description": description,
        }
        if url:
            body["target_url"] = url
        return self._post(project, f"/statuses/{sha}", body)


def _pulls(ref: ChangeRequestRef, suffix: str) -> str:
    return f"/pulls/{ref.number}{suffix}"


def _to_cr(project: str, data: dict[str, Any]) -> ChangeRequest:
    head = as_dict(data["head"])
    base = as_dict(data["base"])
    head_repo = as_dict(head.get("repo") or {}).get("full_name")
    base_repo = as_dict(base.get("repo") or {}).get("full_name")
    return ChangeRequest(
        ref=ChangeRequestRef(project, int(data["number"])),
        title=str(data.get("title") or ""),
        description=str(data.get("body") or ""),
        author=str(as_dict(data.get("user") or {}).get("login") or ""),
        source_branch=str(head["ref"]),
        target_branch=str(base["ref"]),
        head_sha=str(head["sha"]),
        base_sha=str(base["sha"]),
        draft=bool(data.get("draft")),
        is_fork=head_repo is None or head_repo != base_repo,
        web_url=str(data.get("html_url") or ""),
        labels=tuple(
            str(as_dict(lab).get("name", ""))
            for lab in as_list(data.get("labels") or [])
        ),
        state=str(data.get("state") or ""),
    )


def _file_diff(item: dict[str, Any]) -> FileDiff:
    patch_value = item.get("patch")
    has_patch = isinstance(patch_value, str)
    patch = patch_value if isinstance(patch_value, str) else ""
    status = _status(str(item.get("status") or "modified"))
    binary = (
        not has_patch and int(item.get("changes") or 0) == 0 and status != "renamed"
    )
    path = str(item["filename"])
    return FileDiff(
        path=path,
        old_path=str(item.get("previous_filename") or path),
        status=status,
        hunks=parse_patch(patch),
        patch=patch,
        binary=binary,
        truncated=not has_patch,
    )


def _status(raw: str) -> FileStatus:
    if raw == "added":
        return "added"
    if raw == "removed":
        return "deleted"
    if raw == "renamed":
        return "renamed"
    return "modified"


def _issue_comment(data: dict[str, Any]) -> Comment:
    return Comment(
        id=str(data["id"]),
        author=str(as_dict(data.get("user") or {}).get("login") or ""),
        body=str(data.get("body") or ""),
        path=None,
        line=None,
        thread_id=None,
        resolved=False,
    )


def _review_comment(data: dict[str, Any]) -> Comment:
    line = data.get("line") or data.get("original_line")
    return Comment(
        id=str(data["id"]),
        author=str(as_dict(data.get("user") or {}).get("login") or ""),
        body=str(data.get("body") or ""),
        path=str(data["path"]),
        line=int(line) if line is not None else None,
        thread_id=str(data.get("in_reply_to_id") or data["id"]),
        resolved=False,
    )


def _review_entry(comment: InlineComment) -> dict[str, Any]:
    return {
        "path": comment.path,
        "line": comment.line,
        "side": comment.side,
        "body": comment.body,
    }


def _normalise(status: str) -> str:
    return {"failure": "failed", "cancelled": "canceled"}.get(status, status)


def _run_status(data: dict[str, Any]) -> str:
    if data.get("status") == "completed":
        return _normalise(str(data.get("conclusion") or "completed"))
    return str(data.get("status") or "")


def _run(data: dict[str, Any]) -> CiRun:
    return CiRun(
        id=str(data["id"]),
        status=_run_status(data),
        ref=str(data.get("head_branch") or ""),
        sha=str(data.get("head_sha") or ""),
        web_url=str(data.get("html_url") or ""),
        name=str(data.get("name") or "workflow"),
    )


def _job(data: dict[str, Any]) -> CiJob:
    return CiJob(
        id=str(data["id"]),
        name=str(data.get("name") or ""),
        status=_run_status(data),
        stage=str(data.get("workflow_name") or ""),
        web_url=str(data.get("html_url") or ""),
    )
