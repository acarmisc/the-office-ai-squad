from __future__ import annotations

import httpx
import pytest

from code_squad._common.vcs.base import (
    CapabilityError,
    ChangeRequestRef,
    DiffRefs,
    InlineComment,
    StaleHeadError,
    StatusState,
)
from code_squad._common.vcs.gitlab import GitLabProvider
from code_squad._common.vcs.http import HttpClient
from tests.vcs.recorded import GITLAB_BASE, gitlab_recorder, load_json, sent_json, serve

PROJECT_PATH = "/api/v4/projects/acme%2Fweb"
MR_PATH = f"{PROJECT_PATH}/merge_requests/42"
REF = ChangeRequestRef("acme/web", 42)
HEAD = "a" * 40
REFS = DiffRefs(base_sha="b" * 40, start_sha="b" * 40, head_sha=HEAD)


def _provider() -> GitLabProvider:
    return GitLabProvider(
        GITLAB_BASE, "fake-token-for-tests", HttpClient(sleep=lambda _s: None)
    )


def test_inline_comment_is_a_text_discussion_with_position() -> None:
    rec = gitlab_recorder()
    with serve(rec):
        ids = _provider().post_inline_comments(
            REF, HEAD, [InlineComment("src/app.tsx", 2, "Note.")], REFS
        )
    assert ids == ["d9"]
    position = sent_json(rec, "POST", f"{MR_PATH}/discussions")["position"]
    assert position["position_type"] == "text"
    assert position["base_sha"] == REFS.base_sha
    assert position["start_sha"] == REFS.start_sha
    assert position["head_sha"] == HEAD
    assert position["new_path"] == "src/app.tsx"
    assert position["new_line"] == 2
    assert "old_line" not in position


def test_left_side_comment_uses_old_line() -> None:
    rec = gitlab_recorder()
    with serve(rec):
        _provider().post_inline_comments(
            REF, HEAD, [InlineComment("src/app.tsx", 5, "Old side.", side="LEFT")], REFS
        )
    position = sent_json(rec, "POST", f"{MR_PATH}/discussions")["position"]
    assert position["old_line"] == 5
    assert "new_line" not in position


def test_inline_comments_refuse_a_moved_head() -> None:
    rec = gitlab_recorder()
    moved = dict(load_json("gitlab", "merge_request.json"), sha="c" * 40)
    rec.override("GET", MR_PATH, lambda _r: httpx.Response(200, json=moved))
    with serve(rec), pytest.raises(StaleHeadError):
        _provider().post_inline_comments(
            REF, HEAD, [InlineComment("src/app.tsx", 2, "x")], REFS
        )
    assert not [r for r in rec.requests if r.method == "POST"]


def test_approve_sends_head_sha_to_approvals_api() -> None:
    rec = gitlab_recorder()
    with serve(rec):
        assert (
            _provider().submit_review_verdict(REF, HEAD, "APPROVE", "ok") == "approved"
        )
    assert sent_json(rec, "POST", f"{MR_PATH}/approve") == {"sha": HEAD}


def test_comment_verdict_posts_a_note_not_an_approval() -> None:
    rec = gitlab_recorder()
    with serve(rec):
        _provider().submit_review_verdict(REF, HEAD, "REQUEST_CHANGES", "fix it")
    assert sent_json(rec, "POST", f"{MR_PATH}/notes") == {"body": "fix it"}
    assert not [r for r in rec.requests if r.url.path.endswith("/approve")]


def test_upsert_creates_a_note_when_no_marker_exists() -> None:
    rec = gitlab_recorder()
    rec.override(
        "POST", f"{MR_PATH}/notes", lambda _r: httpx.Response(201, json={"id": 911})
    )
    with serve(rec):
        assert (
            _provider().upsert_comment(REF, "<!-- code-squad:new -->", "fresh") == "911"
        )
    assert not [r for r in rec.requests if r.method == "PUT"]


def test_upsert_updates_existing_marker_instead_of_creating() -> None:
    rec = gitlab_recorder()
    marker = "<!-- code-squad:summary:jim -->"
    with serve(rec):
        assert _provider().upsert_comment(REF, marker, f"again\n{marker}") == "900"
    assert sent_json(rec, "PUT", f"{MR_PATH}/notes/900") == {"body": f"again\n{marker}"}
    assert not [r for r in rec.requests if r.method == "POST"]


def test_rate_limited_whoami_honours_retry_after_then_succeeds() -> None:
    sleeps: list[float] = []
    rec = gitlab_recorder()
    attempts = iter(
        [
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(200, json={"id": 1, "username": "code-squad-bot"}),
        ]
    )
    rec.override("GET", "/api/v4/user", lambda _r: next(attempts))
    with serve(rec):
        provider = GitLabProvider(GITLAB_BASE, "t", HttpClient(sleep=sleeps.append))
        assert provider.whoami().username == "code-squad-bot"
    assert sleeps == [3.0]


def test_code_search_disabled_becomes_capability_error() -> None:
    rec = gitlab_recorder()
    rec.override(
        "GET",
        f"{PROJECT_PATH}/search",
        lambda _r: httpx.Response(403, json={"message": "no"}),
    )
    with serve(rec), pytest.raises(CapabilityError):
        _provider().search_repo("acme/web", "greet", HEAD)


def test_reviewers_are_resolved_and_merged_with_existing() -> None:
    rec = gitlab_recorder()
    current = dict(load_json("gitlab", "merge_request.json"), reviewers=[{"id": 3}])
    rec.override("GET", MR_PATH, lambda _r: httpx.Response(200, json=current))
    rec.override("PUT", MR_PATH, lambda _r: httpx.Response(200, json=current))
    with serve(rec):
        _provider().request_reviewers(REF, ["carol"])
    assert sent_json(rec, "PUT", MR_PATH) == {"reviewer_ids": [3, 7]}


def test_protected_branch_lookup_returns_true_only_on_200() -> None:
    with serve(gitlab_recorder()):
        provider = _provider()
        assert provider.is_protected("acme/web", "main") is True
        assert provider.is_protected("acme/web", "develop") is False


def test_status_states_map_to_gitlab_vocabulary() -> None:
    rec = gitlab_recorder()
    with serve(rec):
        _provider().set_status(
            "acme/web", HEAD, StatusState.ERROR, "ai-review/x", "boom", ""
        )
    sent = sent_json(rec, "POST", f"{PROJECT_PATH}/statuses/{HEAD}")
    assert sent["state"] == "failed"
    assert "target_url" not in sent


def test_clone_url_and_oauth_credentials() -> None:
    provider = _provider()
    assert provider.clone_url("acme/web") == f"{GITLAB_BASE}/acme/web.git"
    assert provider.git_credentials("acme/web") == ("oauth2", "fake-token-for-tests")
