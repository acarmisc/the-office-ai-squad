"""Route tables that replay recorded fixtures through respx (no network)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import httpx
import respx

from code_squad._common.vcs.conformance import scenario as s

FIXTURES: Final = Path(__file__).parent / "fixtures"
GITLAB_BASE: Final = "https://gitlab.test"
GITHUB_BASE: Final = "https://api.github.com"
_PROJECT_GL: Final = "acme%2Fweb"
_PROJECT_GH: Final = "acme/web"

Handler = Callable[[httpx.Request], httpx.Response]


def load_json(provider: str, name: str) -> Any:
    return json.loads((FIXTURES / provider / name).read_text(encoding="utf-8"))


def load_text(provider: str, name: str) -> str:
    return (FIXTURES / provider / name).read_text(encoding="utf-8")


def json_response(
    data: object, status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers)


def text_response(content: str) -> httpx.Response:
    return httpx.Response(200, text=content)


def _fixed(provider: str, name: str, status: int = 200) -> Handler:
    def handle(_request: httpx.Request) -> httpx.Response:
        return json_response(load_json(provider, name), status)

    return handle


def _text(provider: str, name: str) -> Handler:
    def handle(_request: httpx.Request) -> httpx.Response:
        return text_response(load_text(provider, name))

    return handle


ADDED_LINE: Final = 2


def _gitlab_discussion(request: httpx.Request) -> httpx.Response:
    position = json.loads(request.content).get("position", {})
    if "new_line" in position and position["new_line"] != ADDED_LINE:
        return json_response({"message": "line_code can't be blank"}, 400)
    return json_response(load_json("gitlab", "discussion_created.json"), 201)


def _github_review(request: httpx.Request) -> httpx.Response:
    for comment in json.loads(request.content).get("comments", []):
        if comment.get("side", "RIGHT") != "RIGHT":
            continue
        lines = {comment.get("line"), comment.get("start_line", comment.get("line"))}
        if lines != {ADDED_LINE}:
            return json_response({"message": "Unprocessable Entity"}, 422)
    return json_response(load_json("github", "review_created.json"), 200)


def _not_found(_request: httpx.Request) -> httpx.Response:
    return json_response({"message": "404 Not found"}, 404)


def _paged(provider: str, first: str, second: str, link: str) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return json_response(load_json(provider, second))
        headers = {"Link": f'<{link}>; rel="next"', "x-next-page": "2"}
        return json_response(load_json(provider, first), headers=headers)

    return handle


class Recorder:
    """Dispatches (method, path) to handlers. Unmatched requests fail loudly."""

    def __init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern[str], Handler]] = []
        self.requests: list[httpx.Request] = []

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        self._routes.append((method, re.compile(pattern), handler))

    def override(self, method: str, pattern: str, handler: Handler) -> None:
        self._routes.insert(0, (method, re.compile(pattern), handler))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.raw_path.decode("ascii").split("?", 1)[0]
        for method, regex, handler in self._routes:
            if request.method == method and regex.fullmatch(path):
                return handler(request)
        raise AssertionError(f"unmocked request: {request.method} {path}")


def gitlab_recorder() -> Recorder:
    api = "/api/v4"
    project = f"{api}/projects/{_PROJECT_GL}"
    mr = f"{project}/merge_requests/42"
    rec = Recorder()
    rec.add("GET", rf"{api}/user", _fixed("gitlab", "user.json"))
    rec.add("GET", rf"{api}/users", _fixed("gitlab", "users.json"))
    rec.add("GET", rf"{project}", _fixed("gitlab", "project.json"))
    rec.add("GET", rf"{mr}", _fixed("gitlab", "merge_request.json"))
    rec.add(
        "GET",
        rf"{project}/merge_requests/43",
        _fixed("gitlab", "merge_request_fork.json"),
    )
    rec.add(
        "GET",
        rf"{mr}/diffs",
        _paged(
            "gitlab",
            "diffs_page1.json",
            "diffs_page2.json",
            f"{GITLAB_BASE}{mr}/diffs?per_page=100&page=2",
        ),
    )
    rec.add(
        "GET",
        rf"{project}/repository/files/src%2Fapp\.tsx/raw",
        _text("gitlab", "app_file.txt"),
    )
    rec.add("GET", rf"{project}/repository/tree", _fixed("gitlab", "tree.json"))
    rec.add("GET", rf"{project}/search", _fixed("gitlab", "search_blobs.json"))
    rec.add("GET", rf"{mr}/discussions", _fixed("gitlab", "discussions.json"))
    rec.add("GET", rf"{mr}/notes", _fixed("gitlab", "notes.json"))
    rec.add("PUT", rf"{mr}/notes/900", _fixed("gitlab", "note_updated.json"))
    rec.add("POST", rf"{mr}/notes", _fixed("gitlab", "note_created.json", 201))
    rec.add("POST", rf"{mr}/discussions", _gitlab_discussion)
    rec.add(
        "PUT", rf"{mr}/discussions/d1", _fixed("gitlab", "discussion_resolved.json")
    )
    rec.add("POST", rf"{mr}/approve", _fixed("gitlab", "approval.json"))
    rec.add(
        "POST", rf"{project}/statuses/{s.HEAD}", _fixed("gitlab", "status.json", 201)
    )
    rec.add("GET", rf"{project}/pipelines", _fixed("gitlab", "pipelines.json"))
    rec.add("GET", rf"{project}/pipelines/5001/jobs", _fixed("gitlab", "jobs.json"))
    rec.add("GET", rf"{project}/jobs/7001/trace", _text("gitlab", "job_trace.txt"))
    rec.add(
        "POST", rf"{project}/repository/branches", _fixed("gitlab", "branch.json", 201)
    )
    rec.add(
        "POST",
        rf"{project}/merge_requests",
        _fixed("gitlab", "merge_request_created.json", 201),
    )
    rec.add(
        "GET",
        rf"{project}/protected_branches/main",
        _fixed("gitlab", "protected_branch.json"),
    )
    rec.add("GET", rf"{project}/protected_branches/develop", _not_found)
    rec.add("GET", rf"{project}/issues/12", _fixed("gitlab", "issue.json"))
    rec.add(
        "POST",
        rf"{project}/issues/12/notes",
        _fixed("gitlab", "note_created.json", 201),
    )
    return rec


def github_recorder() -> Recorder:
    repo = f"/repos/{_PROJECT_GH}"
    rec = Recorder()
    rec.add("GET", r"/user", _fixed("github", "user.json"))
    rec.add("GET", r"/app", _fixed("github", "app.json"))
    rec.add("GET", r"/rate_limit", _fixed("github", "rate_limit.json"))
    rec.add("GET", rf"{repo}", _fixed("github", "repo.json"))
    rec.add("GET", rf"{repo}/pulls/42", _fixed("github", "pull.json"))
    rec.add("GET", rf"{repo}/pulls/43", _fixed("github", "pull_fork.json"))
    rec.add("GET", rf"{repo}/pulls/50", _fixed("github", "pull_created.json"))
    rec.add(
        "GET",
        rf"{repo}/pulls/42/files",
        _paged(
            "github",
            "files_page1.json",
            "files_page2.json",
            f"{GITHUB_BASE}{repo}/pulls/42/files?per_page=100&page=2",
        ),
    )
    rec.add("GET", rf"{repo}/contents/src/app\.tsx", _text("github", "app_file.txt"))
    rec.add("GET", rf"{repo}/contents/src", _fixed("github", "contents_src.json"))
    rec.add("GET", r"/search/code", _fixed("github", "code_search.json"))
    rec.add(
        "GET", rf"{repo}/issues/42/comments", _fixed("github", "issue_comments.json")
    )
    rec.add(
        "POST",
        rf"{repo}/issues/42/comments",
        _fixed("github", "issue_comment_created.json", 201),
    )
    rec.add(
        "GET", rf"{repo}/pulls/42/comments", _fixed("github", "review_comments.json")
    )
    rec.add(
        "PATCH",
        rf"{repo}/issues/comments/900",
        _fixed("github", "issue_comment_updated.json"),
    )
    rec.add("POST", rf"{repo}/pulls/42/reviews", _github_review)
    rec.add("POST", rf"{repo}/statuses/{s.HEAD}", _fixed("github", "status.json", 201))
    rec.add("POST", rf"{repo}/check-runs", _fixed("github", "check_run.json", 201))
    rec.add("GET", rf"{repo}/actions/runs", _fixed("github", "runs.json"))
    rec.add("GET", rf"{repo}/actions/runs/5001/jobs", _fixed("github", "jobs.json"))
    rec.add("GET", rf"{repo}/actions/jobs/7001/logs", _text("github", "job_log.txt"))
    rec.add("POST", rf"{repo}/git/refs", _fixed("github", "git_ref.json", 201))
    rec.add("POST", rf"{repo}/pulls", _fixed("github", "pull_created.json", 201))
    rec.add("GET", rf"{repo}/branches/main", _fixed("github", "branch_protected.json"))
    rec.add(
        "GET", rf"{repo}/branches/develop", _fixed("github", "branch_unprotected.json")
    )
    rec.add("GET", rf"{repo}/issues/12", _fixed("github", "issue.json"))
    rec.add(
        "POST",
        rf"{repo}/issues/12/comments",
        _fixed("github", "issue_comment_created.json", 201),
    )
    rec.add("POST", rf"{repo}/issues/50/labels", _fixed("github", "labels.json"))
    rec.add(
        "POST",
        rf"{repo}/pulls/50/requested_reviewers",
        _fixed("github", "pull_created.json", 201),
    )
    rec.add(
        "POST",
        rf"{repo}/issues/50/assignees",
        _fixed("github", "pull_created.json", 201),
    )
    return rec


def serve(recorder: Recorder) -> respx.MockRouter:
    """A respx router that sends every request to the recorder (use with ``with``)."""
    router = respx.mock(assert_all_called=False, assert_all_mocked=True)
    router.route().mock(side_effect=recorder)
    return router


def sent_json(recorder: Recorder, method: str, path: str) -> Any:
    """JSON body of the last request sent with ``method`` to exactly ``path``."""
    matches = [
        request
        for request in recorder.requests
        if request.method == method
        and request.url.raw_path.decode("ascii").split("?", 1)[0] == path
    ]
    return json.loads(matches[-1].content)
