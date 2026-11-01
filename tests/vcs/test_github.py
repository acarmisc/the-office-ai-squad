from __future__ import annotations

import httpx
import pytest

from code_squad._common.vcs.base import (
    Capability,
    CapabilityError,
    ChangeRequestRef,
    DiffRefs,
    InlineComment,
    StaleHeadError,
)
from code_squad._common.vcs.github import GitHubProvider, TokenAuth
from code_squad._common.vcs.http import HttpClient
from tests.vcs.recorded import GITHUB_BASE, github_recorder, load_json, sent_json, serve

REPO_PATH = "/repos/acme/web"
REF = ChangeRequestRef("acme/web", 42)
HEAD = "a" * 40
REFS = DiffRefs(base_sha="b" * 40, start_sha="b" * 40, head_sha=HEAD)


def _provider() -> GitHubProvider:
    return GitHubProvider(
        GITHUB_BASE,
        auth=TokenAuth("fake-token-for-tests"),
        http=HttpClient(sleep=lambda _s: None),
    )


def test_inline_comments_are_one_batched_review() -> None:
    rec = github_recorder()
    with serve(rec):
        ids = _provider().post_inline_comments(
            REF,
            HEAD,
            [
                InlineComment("src/app.tsx", 2, "one"),
                InlineComment("src/app.tsx", 3, "two", "LEFT"),
            ],
            REFS,
        )
    assert ids == ["906", "906"]
    sent = sent_json(rec, "POST", f"{REPO_PATH}/pulls/42/reviews")
    assert sent["commit_id"] == HEAD
    assert sent["event"] == "COMMENT"
    assert sent["comments"] == [
        {"path": "src/app.tsx", "line": 2, "side": "RIGHT", "body": "one"},
        {"path": "src/app.tsx", "line": 3, "side": "LEFT", "body": "two"},
    ]


def test_no_review_is_posted_for_zero_comments() -> None:
    rec = github_recorder()
    with serve(rec):
        assert _provider().post_inline_comments(REF, HEAD, [], REFS) == []
    assert not [r for r in rec.requests if r.method == "POST"]


def test_stale_head_is_detected_before_reviewing() -> None:
    rec = github_recorder()
    moved = dict(load_json("github", "pull.json"))
    moved["head"] = {"ref": "x", "sha": "c" * 40, "repo": {"full_name": "acme/web"}}
    rec.override(
        "GET", f"{REPO_PATH}/pulls/42", lambda _r: httpx.Response(200, json=moved)
    )
    with serve(rec), pytest.raises(StaleHeadError):
        _provider().get_diff(REF, HEAD)


def test_large_diff_without_patch_is_truncated_but_not_binary() -> None:
    rec = github_recorder()
    large = [{"filename": "src/big.ts", "status": "modified", "changes": 9000}]
    rec.override(
        "GET", f"{REPO_PATH}/pulls/42/files", lambda _r: httpx.Response(200, json=large)
    )
    with serve(rec):
        [only] = _provider().get_diff(REF, HEAD)
    assert only.truncated is True
    assert only.binary is False
    assert only.hunks == ()


def test_fork_pull_request_sets_is_fork_when_head_repo_differs() -> None:
    with serve(github_recorder()):
        assert (
            _provider().get_change_request(ChangeRequestRef("acme/web", 43)).is_fork
            is True
        )
        assert _provider().get_change_request(REF).is_fork is False


def test_deleted_fork_repository_counts_as_fork() -> None:
    rec = github_recorder()
    deleted = dict(load_json("github", "pull.json"))
    deleted["head"] = {"ref": "x", "sha": HEAD, "repo": None}
    rec.override(
        "GET", f"{REPO_PATH}/pulls/42", lambda _r: httpx.Response(200, json=deleted)
    )
    with serve(rec):
        assert _provider().get_change_request(REF).is_fork is True


def test_logs_redirect_is_followed_and_truncated_to_tail() -> None:
    rec = github_recorder()
    blob = "https://pipelines.example.test/blob/job-7001"
    rec.override(
        "GET",
        f"{REPO_PATH}/actions/jobs/7001/logs",
        lambda _r: httpx.Response(302, headers={"Location": blob}),
    )
    rec.override(
        "GET",
        "/blob/job-7001",
        lambda _r: httpx.Response(200, text="x" * 500 + "\nDONE\n"),
    )
    with serve(rec):
        log = _provider().get_job_log("acme/web", "7001", 20)
    assert log.endswith("DONE\n")
    assert len(log.encode()) <= 20


def test_create_change_request_applies_labels_reviewers_and_assignees() -> None:
    rec = github_recorder()
    with serve(rec):
        cr = _provider().create_change_request(
            "acme/web",
            "code-squad/fix-1",
            "main",
            "Fix",
            "Body",
            True,
            ["ai"],
            ["carol"],
            ["alice"],
        )
    assert cr.ref.number == 50
    assert sent_json(rec, "POST", f"{REPO_PATH}/issues/50/labels") == {"labels": ["ai"]}
    assert sent_json(rec, "POST", f"{REPO_PATH}/pulls/50/requested_reviewers") == {
        "reviewers": ["carol"]
    }
    assert sent_json(rec, "POST", f"{REPO_PATH}/issues/50/assignees") == {
        "assignees": ["alice"]
    }


def test_draft_flag_is_sent_on_pull_creation() -> None:
    rec = github_recorder()
    with serve(rec):
        _provider().create_change_request(
            "acme/web", "code-squad/fix-1", "main", "Fix", "B", True, (), (), ()
        )
    assert sent_json(rec, "POST", f"{REPO_PATH}/pulls")["draft"] is True


def test_resolve_thread_is_unsupported_without_graphql() -> None:
    provider = _provider()
    assert Capability.RESOLVE_THREAD not in provider.capabilities
    with pytest.raises(CapabilityError):
        provider.resolve_thread(REF, "T_1")


def test_upsert_creates_when_marker_is_absent() -> None:
    rec = github_recorder()
    with serve(rec):
        assert (
            _provider().upsert_comment(REF, "<!-- code-squad:new -->", "fresh") == "905"
        )
    assert sent_json(rec, "POST", f"{REPO_PATH}/issues/42/comments") == {
        "body": "fresh"
    }
    assert not [r for r in rec.requests if r.method == "PATCH"]


def test_upsert_patches_existing_marker_comment() -> None:
    rec = github_recorder()
    marker = "<!-- code-squad:summary:jim -->"
    with serve(rec):
        assert _provider().upsert_comment(REF, marker, f"again\n{marker}") == "900"
    assert sent_json(rec, "PATCH", f"{REPO_PATH}/issues/comments/900") == {
        "body": f"again\n{marker}"
    }


def test_rate_limit_parses_core_resource() -> None:
    with serve(github_recorder()):
        rate = _provider().rate_limit()
    assert rate is not None
    assert (rate.limit, rate.remaining, rate.reset_epoch) == (5000, 4990, 1800000000)


def test_clone_url_maps_api_host_to_github_com() -> None:
    assert _provider().clone_url("acme/web") == "https://github.com/acme/web.git"
    ghes = GitHubProvider("https://ghe.example.test/api/v3", auth=TokenAuth("t"))
    assert ghes.clone_url("acme/web") == "https://ghe.example.test/acme/web.git"


class _AppIdentity(TokenAuth):
    kind = "app"


def _app_provider() -> GitHubProvider:
    return GitHubProvider(
        GITHUB_BASE,
        auth=_AppIdentity("fake-token-for-tests"),
        http=HttpClient(sleep=lambda _s: None),
    )


def test_adv06_github_app_identity_is_the_slug_with_bot_suffix() -> None:
    with serve(github_recorder()):
        assert _app_provider().whoami().username == "code-squad[bot]"


def test_adv06_a_github_app_does_not_edit_a_comment_by_a_plain_login() -> None:
    rec = github_recorder()
    marker = "<!-- code-squad:summary:jim -->"
    with serve(rec):
        _app_provider().upsert_comment(REF, marker, f"again\n{marker}")
    assert not [r for r in rec.requests if r.method == "PATCH"]
    assert sent_json(rec, "POST", f"{REPO_PATH}/issues/42/comments")["body"].startswith(
        "again"
    )


def test_adv06_a_github_app_edits_its_own_comment() -> None:
    rec = github_recorder()
    marker = "<!-- code-squad:summary:jim -->"
    own = [
        {
            "id": 900,
            "body": f"earlier\n{marker}",
            "user": {"login": "code-squad[bot]"},
        }
    ]
    rec.override(
        "GET",
        rf"{REPO_PATH}/issues/42/comments",
        lambda _r: httpx.Response(200, json=own),
    )
    with serve(rec):
        assert _app_provider().upsert_comment(REF, marker, f"new\n{marker}") == "900"
    assert [r for r in rec.requests if r.method == "PATCH"]


def test_adv07_multi_line_range_sends_start_line_and_line() -> None:
    rec = github_recorder()
    review = load_json("github", "review_created.json")
    rec.override(
        "POST",
        rf"{REPO_PATH}/pulls/42/reviews",
        lambda _r: httpx.Response(200, json=review),
    )
    comment = InlineComment("src/app.tsx", 3, "range", start_line=2)
    with serve(rec):
        _provider().post_inline_comments(REF, HEAD, [comment], REFS)
    sent = sent_json(rec, "POST", f"{REPO_PATH}/pulls/42/reviews")
    assert sent["comments"] == [
        {
            "path": "src/app.tsx",
            "line": 3,
            "side": "RIGHT",
            "body": "range",
            "start_line": 2,
            "start_side": "RIGHT",
        }
    ]


def test_adv07_renamed_file_is_addressed_by_its_new_path() -> None:
    rec = github_recorder()
    comment = InlineComment("src/app.tsx", 2, "renamed", old_path="src/old.tsx")
    with serve(rec):
        _provider().post_inline_comments(REF, HEAD, [comment], REFS)
    sent = sent_json(rec, "POST", f"{REPO_PATH}/pulls/42/reviews")
    assert sent["comments"][0]["path"] == "src/app.tsx"


def test_adv07_rejected_comment_falls_back_per_comment_and_keeps_the_others() -> None:
    rec = github_recorder()
    comments = [
        InlineComment("src/app.tsx", 2, "good"),
        InlineComment("src/app.tsx", 1, "context"),
    ]
    with serve(rec):
        ids = _provider().post_inline_comments(REF, HEAD, comments, REFS)
    assert ids == ["906", ""]
    reviews = [r for r in rec.requests if r.url.path.endswith("/pulls/42/reviews")]
    assert len(reviews) == 3


def test_adv06_github_comment_by_another_login_with_marker_is_not_edited() -> None:
    rec = github_recorder()
    marker = "<!-- code-squad:summary:jim -->"
    spoof = [{"id": 950, "body": f"x\n{marker}", "user": {"login": "mallory"}}]
    rec.override(
        "GET",
        rf"{REPO_PATH}/issues/42/comments",
        lambda _r: httpx.Response(200, json=spoof),
    )
    with serve(rec):
        _provider().upsert_comment(REF, marker, f"real\n{marker}")
    assert not [r for r in rec.requests if r.method == "PATCH"]


def test_adv13_large_file_is_capped_before_decoding() -> None:
    rec = github_recorder()
    huge = ("y" * 1000 + "\n") * 2000
    rec.override(
        "GET",
        rf"{REPO_PATH}/contents/src/app\.tsx",
        lambda _r: httpx.Response(200, text=huge),
    )
    with serve(rec):
        text = _provider().read_file("acme/web", "src/app.tsx", HEAD)
    assert len(text.encode("utf-8")) <= 1_048_576 + 200
    assert "truncated" in text
