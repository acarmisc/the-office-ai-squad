from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest

from code_squad._common import webhooks
from code_squad._common.webhooks import (
    DeliveryDeduper,
    WebhookEvent,
    decide_trigger,
    parse_github_event,
    parse_gitlab_event,
    verify_github,
    verify_gitlab,
)

BOT = "code-squad-bot"
SECRET = "fake-webhook-secret-for-tests"
ALL_EVENTS: tuple[str, ...] = (
    "change_request_opened",
    "change_request_updated",
    "change_request_ready",
    "review_requested",
    "comment",
    "issue_assigned",
)


def _cr(**overrides: Any) -> WebhookEvent:
    base: dict[str, Any] = {
        "provider": "github",
        "kind": "change_request",
        "action": "opened",
        "project": "acme/web",
        "number": 42,
        "author": "alice",
        "title": "Add greeting",
        "head_sha": "a" * 40,
    }
    base.update(overrides)
    return WebhookEvent(**base)


def _decide(event: WebhookEvent, **overrides: Any) -> webhooks.TriggerDecision:
    options: dict[str, Any] = {
        "bot_username": BOT,
        "on_push": True,
        "allowed_commenters": ("alice", "bob"),
        "events": ALL_EVENTS,
    }
    options.update(overrides)
    return decide_trigger(event, **options)


def _gh_sig(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ----- signatures ------------------------------------------------------------


def test_gitlab_token_accepts_only_the_exact_secret() -> None:
    assert verify_gitlab({"X-Gitlab-Token": SECRET}, SECRET) is True
    assert verify_gitlab({"x-gitlab-token": SECRET}, SECRET) is True
    assert verify_gitlab({"X-Gitlab-Token": SECRET + "x"}, SECRET) is False
    assert verify_gitlab({}, SECRET) is False
    assert verify_gitlab({"X-Gitlab-Token": ""}, "") is False


def test_github_signature_is_hmac_over_the_raw_body() -> None:
    body = json.dumps({"action": "opened"}).encode()
    assert verify_github({"X-Hub-Signature-256": _gh_sig(body)}, body, SECRET) is True


@pytest.mark.parametrize(
    ("headers", "body"),
    [
        ({"X-Hub-Signature-256": _gh_sig(b'{"a":1}')}, b'{"a":2}'),
        ({"X-Hub-Signature-256": _gh_sig(b"{}", "wrong-secret")}, b"{}"),
        ({"X-Hub-Signature-256": "sha1=" + "0" * 40}, b"{}"),
        ({}, b"{}"),
    ],
)
def test_github_rejects_tampered_wrong_or_missing_signatures(
    headers: dict[str, str], body: bytes
) -> None:
    assert verify_github(headers, body, SECRET) is False


def test_signature_checks_use_constant_time_compare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    real = hmac.compare_digest

    def spy(left: Any, right: Any) -> bool:
        calls.append("compare_digest")
        return bool(real(left, right))

    monkeypatch.setattr(hmac, "compare_digest", spy)
    verify_gitlab({"X-Gitlab-Token": SECRET}, SECRET)
    verify_github({"X-Hub-Signature-256": _gh_sig(b"x")}, b"x", SECRET)
    assert calls == ["compare_digest", "compare_digest"]


# ----- dedupe ----------------------------------------------------------------


def test_deduper_checks_without_recording() -> None:
    deduper = DeliveryDeduper()
    assert deduper.is_recorded("a") is False
    assert deduper.is_recorded("a") is False
    deduper.record("a")
    assert deduper.is_recorded("a") is True


def test_deduper_evicts_the_oldest_recorded_id() -> None:
    deduper = DeliveryDeduper(capacity=2)
    deduper.record("a")
    deduper.record("b")
    deduper.record("c")
    assert deduper.is_recorded("a") is False
    assert deduper.is_recorded("b") is True
    assert deduper.is_recorded("c") is True


# ----- parsing ---------------------------------------------------------------


def test_parse_gitlab_merge_request_hook() -> None:
    payload = {
        "object_kind": "merge_request",
        "project": {"path_with_namespace": "acme/web"},
        "user": {"username": "alice"},
        "object_attributes": {
            "iid": 42,
            "action": "update",
            "title": "Draft: Add greeting",
            "draft": True,
            "description": "Body",
            "last_commit": {"id": "a" * 40},
        },
        "labels": [{"title": "frontend"}],
        "reviewers": [{"username": BOT}],
        "assignees": [],
    }
    event = parse_gitlab_event({"X-Gitlab-Event-UUID": "uuid-1"}, payload)
    assert event is not None
    assert (event.provider, event.kind, event.action) == (
        "gitlab",
        "change_request",
        "update",
    )
    assert (event.project, event.number, event.author) == ("acme/web", 42, "alice")
    assert event.head_sha == "a" * 40
    assert event.draft is True
    assert event.labels == ("frontend",)
    assert event.reviewers == (BOT,)
    assert event.delivery_id == "uuid-1"


def test_parse_gitlab_note_on_merge_request_and_issue() -> None:
    base = {
        "object_kind": "note",
        "project": {"path_with_namespace": "acme/web"},
        "user": {"username": "bob"},
    }
    on_mr = parse_gitlab_event(
        {},
        {
            **base,
            "object_attributes": {
                "note": "@code-squad-bot review",
                "noteable_type": "MergeRequest",
            },
            "merge_request": {"iid": 42, "last_commit": {"id": "b" * 40}},
        },
    )
    on_issue = parse_gitlab_event(
        {},
        {
            **base,
            "object_attributes": {"note": "/squad implement", "noteable_type": "Issue"},
            "issue": {"iid": 7},
        },
    )
    assert on_mr is not None and (on_mr.kind, on_mr.number, on_mr.body) == (
        "comment",
        42,
        "@code-squad-bot review",
    )
    assert on_issue is not None and (on_issue.kind, on_issue.number) == ("issue", 7)


def test_parse_gitlab_issue_hook_and_unknown_kinds() -> None:
    issue = parse_gitlab_event(
        {},
        {
            "object_kind": "issue",
            "project": {"path_with_namespace": "acme/web"},
            "user": {"username": "alice"},
            "object_attributes": {
                "iid": 7,
                "action": "update",
                "title": "Fix it",
                "description": "d",
            },
            "assignees": [{"username": BOT}],
            "labels": [],
        },
    )
    assert issue is not None and issue.kind == "issue"
    assert issue.assignees == (BOT,)
    assert parse_gitlab_event({}, {"object_kind": "push"}) is None


def test_parse_github_pull_request_and_comments() -> None:
    pr = parse_github_event(
        {"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d-1"},
        {
            "action": "review_requested",
            "sender": {"login": "alice"},
            "repository": {"full_name": "acme/web"},
            "pull_request": {
                "number": 42,
                "title": "Add greeting",
                "body": "b",
                "draft": False,
                "head": {"sha": "c" * 40},
                "labels": [{"name": "frontend"}],
                "requested_reviewers": [{"login": BOT}],
                "assignees": [],
            },
        },
    )
    assert pr is not None
    assert (pr.kind, pr.action, pr.number, pr.author) == (
        "change_request",
        "review_requested",
        42,
        "alice",
    )
    assert pr.reviewers == (BOT,)
    assert pr.delivery_id == "d-1"

    on_pr = parse_github_event(
        {"X-GitHub-Event": "issue_comment"},
        {
            "action": "created",
            "repository": {"full_name": "acme/web"},
            "issue": {
                "number": 42,
                "pull_request": {"url": "x"},
                "labels": [],
                "assignees": [],
            },
            "comment": {"body": "@code-squad-bot review", "user": {"login": "bob"}},
        },
    )
    assert on_pr is not None and (on_pr.kind, on_pr.number, on_pr.author) == (
        "comment",
        42,
        "bob",
    )

    on_issue = parse_github_event(
        {"X-GitHub-Event": "issue_comment"},
        {
            "action": "created",
            "repository": {"full_name": "acme/web"},
            "issue": {"number": 9, "labels": [], "assignees": []},
            "comment": {"body": "/squad implement", "user": {"login": "bob"}},
        },
    )
    assert on_issue is not None and (on_issue.kind, on_issue.action) == (
        "issue",
        "comment",
    )


def test_parse_github_issue_assignment_and_unknown_events() -> None:
    issue = parse_github_event(
        {"X-GitHub-Event": "issues"},
        {
            "action": "assigned",
            "sender": {"login": "alice"},
            "repository": {"full_name": "acme/web"},
            "assignee": {"login": BOT},
            "issue": {
                "number": 9,
                "title": "Add button",
                "body": "",
                "labels": [],
                "assignees": [],
            },
        },
    )
    assert issue is not None
    assert issue.assignees == (BOT,)
    assert parse_github_event({"X-GitHub-Event": "ping"}, {}) is None


# ----- trigger rules ---------------------------------------------------------


def test_bot_authored_events_are_ignored_for_loop_prevention() -> None:
    decision = _decide(_cr(author=BOT, action="synchronize"))
    assert decision.run is False and "bot itself" in decision.reason


def test_review_requested_from_bot_runs_mr_review() -> None:
    decision = _decide(_cr(action="review_requested", reviewers=(BOT,)), on_push=False)
    assert (decision.run, decision.intent) == (True, "mr_review")


def test_assigned_to_bot_runs_mr_review_even_without_push_trigger() -> None:
    decision = _decide(
        _cr(action="assigned", assignees=("CODE-SQUAD-BOT",)), on_push=False
    )
    assert decision.run is True and decision.intent == "mr_review"


def test_push_updates_run_only_when_on_push_is_enabled() -> None:
    update = _cr(action="synchronize")
    assert _decide(update, on_push=True).run is True
    off = _decide(update, on_push=False)
    assert off.run is False and "disabled" in off.reason


def _gitlab_mr_update(
    *,
    changes: dict[str, Any] | None = None,
    reviewers: list[str] | None = None,
    assignees: list[str] | None = None,
) -> dict[str, Any]:
    """A GitLab merge_request "update" hook with optional reviewer/assignee changes."""
    return {
        "object_kind": "merge_request",
        "project": {"path_with_namespace": "acme/web"},
        "user": {"username": "alice"},
        "object_attributes": {
            "iid": 42,
            "action": "update",
            "title": "Add greeting",
            "description": "Body",
            "last_commit": {"id": "a" * 40},
        },
        "labels": [],
        "reviewers": [{"username": name} for name in reviewers or []],
        "assignees": [{"username": name} for name in assignees or []],
        "changes": changes or {},
    }


def _users(*names: str) -> list[dict[str, str]]:
    return [{"username": name} for name in names]


def test_gitlab_update_adding_bot_as_reviewer_runs_review_without_push() -> None:
    payload = _gitlab_mr_update(
        changes={
            "reviewers": {"previous": [], "current": _users(BOT)},
        },
        reviewers=[BOT],
    )
    event = parse_gitlab_event({}, payload)
    assert event is not None and event.newly_requested == (BOT,)
    decision = _decide(event, on_push=False)
    assert (decision.run, decision.intent) == (True, "mr_review")


def test_gitlab_update_adding_bot_as_assignee_runs_review_without_push() -> None:
    payload = _gitlab_mr_update(
        changes={
            "assignees": {"previous": _users("alice"), "current": _users("alice", BOT)}
        },
        assignees=["alice", BOT],
    )
    event = parse_gitlab_event({}, payload)
    assert event is not None and event.newly_requested == (BOT,)
    decision = _decide(event, on_push=False)
    assert (decision.run, decision.intent) == (True, "mr_review")


def test_gitlab_update_without_reviewer_change_is_ignored_without_push() -> None:
    payload = _gitlab_mr_update(
        changes={"title": {"previous": "Old", "current": "Add greeting"}},
        reviewers=[BOT],
    )
    event = parse_gitlab_event({}, payload)
    assert event is not None and event.newly_requested == ()
    decision = _decide(event, on_push=False)
    assert decision.run is False and "disabled" in decision.reason


def test_gitlab_update_where_bot_was_already_reviewer_is_not_retriggered() -> None:
    payload = _gitlab_mr_update(
        changes={
            "reviewers": {
                "previous": _users("Code-Squad-Bot"),
                "current": _users("code-squad-bot", "bob"),
            }
        },
        reviewers=[BOT, "bob"],
    )
    event = parse_gitlab_event({}, payload)
    assert event is not None and event.newly_requested == ("bob",)
    assert _decide(event, on_push=False).run is False
    with_push = _decide(event, on_push=True)
    assert with_push.run is True and with_push.intent == "mr_review"
    assert "on_push" in with_push.reason


def test_draft_and_wip_change_requests_are_skipped_unless_allowed() -> None:
    assert _decide(_cr(draft=True)).run is False
    assert _decide(_cr(draft=True), skip_draft=False).run is True
    wip = _decide(_cr(title="WIP: rework"))
    assert wip.run is False and "WIP" in wip.reason
    assert _decide(_cr(title="[draft] thing")).run is False


def test_skip_labels_block_change_requests_and_issues() -> None:
    assert _decide(_cr(labels=("skip-squad",))).run is False
    assert (
        _decide(_cr(labels=("Skip-Squad",)), skip_labels=("skip-squad",)).run is False
    )
    assert _decide(_cr(labels=("other",))).run is True
    issue = WebhookEvent(
        "github",
        "issue",
        "assigned",
        "acme/web",
        9,
        "alice",
        labels=("skip-squad",),
        assignees=(BOT,),
    )
    assert _decide(issue).run is False


def test_closed_or_unknown_change_request_actions_are_ignored() -> None:
    decision = _decide(_cr(action="closed"))
    assert decision.run is False and "not handled" in decision.reason


def test_mention_from_allowed_commenter_runs_mr_review() -> None:
    comment = WebhookEvent(
        "github",
        "comment",
        "created",
        "acme/web",
        42,
        "alice",
        body="thanks @code-squad-bot please look",
    )
    assert _decide(comment).intent == "mr_review"


def test_slash_commands_map_to_intents_for_allowed_commenters() -> None:
    cases = {
        "/squad review": "mr_review",
        "/squad sec": "sec_review",
        "/squad implement": "implement",
        "/squad help": "help",
    }
    for text, intent in cases.items():
        event = WebhookEvent(
            "gitlab", "comment", "created", "acme/web", 42, "bob", body=text
        )
        decision = _decide(event)
        assert (decision.run, decision.intent) == (True, intent), text


def test_comments_from_unauthorised_users_never_trigger() -> None:
    comment = WebhookEvent(
        "github", "comment", "created", "acme/web", 42, "mallory", body="/squad sec"
    )
    decision = _decide(comment)
    assert decision.run is False and "allowed_commenters" in decision.reason


def test_comment_without_mention_or_command_is_ignored() -> None:
    comment = WebhookEvent(
        "github", "comment", "created", "acme/web", 42, "alice", body="looks good"
    )
    assert _decide(comment).run is False


def test_mention_of_a_longer_bot_name_does_not_match() -> None:
    comment = WebhookEvent(
        "github",
        "comment",
        "created",
        "acme/web",
        42,
        "alice",
        body="@code-squad-bot2 review",
    )
    assert _decide(comment).run is False


def test_github_app_bot_name_is_matched_literally() -> None:
    comment = WebhookEvent(
        "github",
        "comment",
        "created",
        "acme/web",
        42,
        "alice",
        body="@code-squad[bot] review",
    )
    assert _decide(comment, bot_username="code-squad[bot]").run is True


def test_issue_assigned_to_bot_runs_implement() -> None:
    issue = WebhookEvent(
        "github", "issue", "assigned", "acme/web", 9, "alice", assignees=(BOT,)
    )
    decision = _decide(issue, allowed_assigners=("alice",))
    assert (decision.run, decision.intent) == (True, "implement")
    other = WebhookEvent(
        "github", "issue", "assigned", "acme/web", 9, "alice", assignees=("carol",)
    )
    assert _decide(other, allowed_assigners=("alice",)).run is False


def test_issue_assignment_is_ignored_unless_the_assigner_is_allowed() -> None:
    issue = WebhookEvent(
        "github", "issue", "assigned", "acme/web", 9, "mallory", assignees=(BOT,)
    )
    unset = _decide(issue)
    assert unset.run is False
    assert "allowed_assigners is empty" in unset.reason
    denied = _decide(issue, allowed_assigners=("alice",))
    assert denied.run is False
    assert denied.reason == "assigner is not in trigger.allowed_assigners"
    allowed = WebhookEvent(
        "github", "issue", "assigned", "acme/web", 9, "Alice", assignees=(BOT,)
    )
    assert _decide(allowed, allowed_assigners=("alice",)).run is True


def test_gitlab_issue_is_ignored_for_an_assigner_outside_the_list() -> None:
    payload = {
        "object_kind": "issue",
        "project": {"path_with_namespace": "acme/web"},
        "user": {"username": "mallory"},
        "object_attributes": {"iid": 7, "action": "open", "title": "Fix it"},
        "assignees": [{"username": BOT}],
        "labels": [],
    }
    event = parse_gitlab_event({}, payload)
    assert event is not None and event.author == "mallory"
    assert _decide(event, allowed_assigners=("alice",)).run is False
    payload["user"] = {"username": "alice"}
    event = parse_gitlab_event({}, payload)
    assert event is not None
    assert _decide(event, allowed_assigners=("alice",)).run is True


def test_issue_comments_support_implement_and_help_but_not_reviews() -> None:
    implement = WebhookEvent(
        "gitlab", "issue", "comment", "acme/web", 9, "bob", body="/squad implement"
    )
    assert _decide(implement).intent == "implement"
    review = WebhookEvent(
        "gitlab", "issue", "comment", "acme/web", 9, "bob", body="/squad review"
    )
    decision = _decide(review)
    assert decision.run is False and "change requests" in decision.reason
    mention = WebhookEvent(
        "gitlab", "issue", "comment", "acme/web", 9, "bob", body="@code-squad-bot"
    )
    assert _decide(mention).intent == "help"


# ----- configurable trigger rules --------------------------------------------


def test_wip_titles_are_skipped_only_when_skip_wip_titles_is_on() -> None:
    wip = _cr(title="WIP: rework")
    assert _decide(wip, skip_wip_titles=True).run is False
    assert _decide(wip, skip_wip_titles=False).run is True
    draft_tag = _cr(title="[draft] thing")
    assert _decide(draft_tag, skip_wip_titles=False).run is True


def test_other_bot_authors_are_skipped_only_when_skip_bot_authors_is_on() -> None:
    dependabot = _cr(author="dependabot[bot]")
    decision = _decide(dependabot, skip_bot_authors=True)
    assert decision.run is False and "another bot" in decision.reason
    assert _decide(dependabot, skip_bot_authors=False).run is True
    renovate = _cr(author="renovate-bot")
    assert _decide(renovate, skip_bot_authors=True).run is False
    assert _decide(_cr(author="alice"), skip_bot_authors=True).run is True


def test_other_bot_comments_are_skipped_only_when_skip_bot_authors_is_on() -> None:
    comment = WebhookEvent(
        "github",
        "comment",
        "created",
        "acme/web",
        42,
        "release_bot",
        body="@code-squad-bot review",
    )
    assert _decide(comment, allowed_commenters=("release_bot",)).run is False
    decision = _decide(
        comment, allowed_commenters=("release_bot",), skip_bot_authors=False
    )
    assert (decision.run, decision.intent) == (True, "mr_review")


def test_bot_loop_prevention_ignores_the_bot_even_when_skip_bot_authors_is_off() -> (
    None
):
    decision = _decide(_cr(author=BOT), skip_bot_authors=False)
    assert decision.run is False and "bot itself" in decision.reason


def test_events_not_listed_in_trigger_events_are_ignored() -> None:
    update = _cr(action="synchronize")
    decision = _decide(update, events=("change_request_opened",))
    assert decision.run is False
    assert decision.reason == "event not enabled in trigger.events"
    assert _decide(update, events=("change_request_updated",)).run is True


def test_review_request_needs_review_requested_in_trigger_events() -> None:
    request = _cr(action="review_requested", reviewers=(BOT,))
    decision = _decide(request, events=("change_request_opened",), on_push=False)
    assert decision.reason == "event not enabled in trigger.events"
    allowed = _decide(request, events=("review_requested",), on_push=False)
    assert allowed.run is True


def test_comments_and_issue_assignments_follow_trigger_events() -> None:
    comment = WebhookEvent(
        "github", "comment", "created", "acme/web", 42, "alice", body="/squad sec"
    )
    decision = _decide(comment, events=("issue_assigned",))
    assert decision.reason == "event not enabled in trigger.events"
    assert _decide(comment, events=("comment",)).run is True
    issue = WebhookEvent(
        "github", "issue", "assigned", "acme/web", 9, "alice", assignees=(BOT,)
    )
    assert _decide(issue, events=()).reason == "event not enabled in trigger.events"
    assert (
        _decide(issue, events=("issue_assigned",), allowed_assigners=("alice",)).run
        is True
    )


def test_unhandled_actions_keep_their_own_reason_under_any_events() -> None:
    decision = _decide(_cr(action="closed"), events=())
    assert decision.run is False and "not handled" in decision.reason
