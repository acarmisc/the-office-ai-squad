"""Webhook verification, delivery de-duplication and trigger rules (pure functions)."""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

Provider = Literal["gitlab", "github"]
Kind = Literal["change_request", "comment", "issue"]
Intent = Literal["mr_review", "sec_review", "implement", "help"]

DEFAULT_SKIP_LABELS: Final[tuple[str, ...]] = ("skip-squad",)
_PUSH_ACTIONS: Final = frozenset(
    {
        "open",
        "opened",
        "update",
        "updated",
        "synchronize",
        "reopened",
        "ready_for_review",
    }
)
_ASSIGNMENT_ACTIONS: Final = frozenset(
    {"review_requested", "assigned", "open", "opened"}
)
_ISSUE_ASSIGNMENT_ACTIONS: Final = frozenset({"assigned", "open", "opened"})
_WIP_PREFIXES: Final = ("wip", "draft", "[wip]", "[draft]")
_COMMAND: Final = re.compile(r"/squad\s+(review|sec|implement|help)\b", re.IGNORECASE)
_COMMAND_INTENT: Final[dict[str, Intent]] = {
    "review": "mr_review",
    "sec": "sec_review",
    "implement": "implement",
    "help": "help",
}


@dataclass(frozen=True)
class WebhookEvent:
    provider: Provider
    kind: Kind
    action: str
    project: str
    number: int
    author: str
    body: str = ""
    head_sha: str = ""
    labels: tuple[str, ...] = ()
    draft: bool = False
    title: str = ""
    reviewers: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    # Lowercased usernames newly added as reviewer or assignee by this event (GitLab
    # "update" hooks report these as changes, not as the action).
    newly_requested: tuple[str, ...] = ()
    delivery_id: str = ""


@dataclass(frozen=True)
class TriggerDecision:
    run: bool
    intent: Intent | None
    reason: str


def verify_gitlab(headers: Mapping[str, str], secret: str) -> bool:
    token = _header(headers, "x-gitlab-token")
    if not token or not secret:
        return False
    return hmac.compare_digest(token.encode("utf-8"), secret.encode("utf-8"))


def verify_github(headers: Mapping[str, str], raw_body: bytes, secret: str) -> bool:
    signature = _header(headers, "x-hub-signature-256")
    if not signature or not secret or not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={digest}".encode(), signature.encode("utf-8"))


class DeliveryDeduper:
    """Bounded LRU of delivery ids. ``seen`` records the id and reports repeats."""

    def __init__(self, capacity: int = 10_000) -> None:
        self._capacity = capacity
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def seen(self, delivery_id: str) -> bool:
        with self._lock:
            if delivery_id in self._seen:
                self._seen.move_to_end(delivery_id)
                return True
            self._seen[delivery_id] = None
            if len(self._seen) > self._capacity:
                self._seen.popitem(last=False)
            return False


def parse_gitlab_event(
    headers: Mapping[str, str], payload: Mapping[str, Any]
) -> WebhookEvent | None:
    delivery = _header(headers, "x-gitlab-event-uuid") or ""
    kind_name = str(payload.get("object_kind") or "")
    if kind_name == "merge_request":
        return _gitlab_merge_request(payload, delivery)
    if kind_name == "note":
        return _gitlab_note(payload, delivery)
    if kind_name == "issue":
        return _gitlab_issue(payload, delivery)
    return None


def parse_github_event(
    headers: Mapping[str, str], payload: Mapping[str, Any]
) -> WebhookEvent | None:
    delivery = _header(headers, "x-github-delivery") or ""
    event = _header(headers, "x-github-event") or ""
    if event == "pull_request":
        return _github_pull_request(payload, delivery)
    if event in {"issue_comment", "pull_request_review_comment"}:
        return _github_comment(event, payload, delivery)
    if event == "issues":
        return _github_issue(payload, delivery)
    return None


def decide_trigger(
    event: WebhookEvent,
    *,
    bot_username: str,
    on_push: bool,
    allowed_commenters: Sequence[str],
    skip_labels: Sequence[str] = DEFAULT_SKIP_LABELS,
    skip_draft: bool = True,
) -> TriggerDecision:
    bot = bot_username.lower()
    if event.author.lower() == bot:
        return _ignore("event authored by the bot itself")
    if event.kind == "change_request":
        return _change_request(event, bot, on_push, skip_labels, skip_draft)
    if event.kind == "comment":
        return _comment(event, bot, allowed_commenters, skip_labels, skip_draft)
    return _issue(event, bot, allowed_commenters, skip_labels)


def _change_request(
    event: WebhookEvent,
    bot: str,
    on_push: bool,
    skip_labels: Sequence[str],
    skip_draft: bool,
) -> TriggerDecision:
    involved = bot in _lower(event.reviewers) or bot in _lower(event.assignees)
    newly = bot in _lower(event.newly_requested)
    if newly or (involved and event.action in _ASSIGNMENT_ACTIONS):
        skipped = _skip_reason(event, skip_labels, skip_draft)
        if skipped:
            return _ignore(skipped)
        return TriggerDecision(
            True, "mr_review", "review requested from or assigned to the bot"
        )
    if event.action in _PUSH_ACTIONS:
        if not on_push:
            return _ignore("push-triggered reviews are disabled for this project")
        skipped = _skip_reason(event, skip_labels, skip_draft)
        if skipped:
            return _ignore(skipped)
        return TriggerDecision(True, "mr_review", "change request updated (on_push)")
    return _ignore(f"change request action '{event.action}' is not handled")


def _comment(
    event: WebhookEvent,
    bot: str,
    allowed: Sequence[str],
    skip_labels: Sequence[str],
    skip_draft: bool,
) -> TriggerDecision:
    if event.author.lower() not in _lower(allowed):
        return _ignore("commenter is not in allowed_commenters")
    intent = _requested_intent(event.body, bot, default="mr_review")
    if intent is None:
        return _ignore("comment has no @mention or /squad command")
    skipped = _skip_reason(event, skip_labels, skip_draft)
    if skipped:
        return _ignore(skipped)
    return TriggerDecision(True, intent, f"comment requested {intent}")


def _issue(
    event: WebhookEvent,
    bot: str,
    allowed: Sequence[str],
    skip_labels: Sequence[str],
) -> TriggerDecision:
    if event.action == "comment":
        return _issue_comment(event, bot, allowed, skip_labels)
    if bot in _lower(event.assignees) and event.action in _ISSUE_ASSIGNMENT_ACTIONS:
        if _labels_skipped(event.labels, skip_labels):
            return _ignore("issue carries a skip label")
        return TriggerDecision(True, "implement", "issue assigned to the bot")
    return _ignore(f"issue action '{event.action}' is not handled")


def _issue_comment(
    event: WebhookEvent,
    bot: str,
    allowed: Sequence[str],
    skip_labels: Sequence[str],
) -> TriggerDecision:
    if event.author.lower() not in _lower(allowed):
        return _ignore("commenter is not in allowed_commenters")
    intent = _requested_intent(event.body, bot, default="help")
    if intent in ("mr_review", "sec_review"):
        return _ignore("review commands apply to change requests, not issues")
    if intent is None:
        return _ignore("comment has no @mention or /squad command")
    if _labels_skipped(event.labels, skip_labels):
        return _ignore("issue carries a skip label")
    return TriggerDecision(True, intent, f"issue comment requested {intent}")


def _requested_intent(body: str, bot: str, *, default: Intent) -> Intent | None:
    command = _COMMAND.search(body)
    if command is not None:
        return _COMMAND_INTENT[command.group(1).lower()]
    mention = re.search(rf"(?<![\w@])@{re.escape(bot)}(?![\w-])", body, re.IGNORECASE)
    return default if mention is not None else None


def _skip_reason(
    event: WebhookEvent, skip_labels: Sequence[str], skip_draft: bool
) -> str | None:
    if skip_draft and event.draft:
        return "draft change request is skipped"
    if event.title.lower().lstrip().startswith(_WIP_PREFIXES):
        return "WIP or draft title is skipped"
    if _labels_skipped(event.labels, skip_labels):
        return "change request carries a skip label"
    return None


def _labels_skipped(labels: Sequence[str], skip_labels: Sequence[str]) -> bool:
    return bool(set(_lower(labels)) & set(_lower(skip_labels)))


def _ignore(reason: str) -> TriggerDecision:
    return TriggerDecision(False, None, reason)


def _lower(values: Sequence[str]) -> list[str]:
    return [value.lower() for value in values]


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return str(value)
    return None


def _gitlab_merge_request(payload: Mapping[str, Any], delivery: str) -> WebhookEvent:
    attrs = _map(payload.get("object_attributes"))
    last = _map(attrs.get("last_commit"))
    return WebhookEvent(
        provider="gitlab",
        kind="change_request",
        action=str(attrs.get("action") or ""),
        project=_project_path(payload),
        number=int(attrs.get("iid") or 0),
        author=_username(payload.get("user")),
        body=str(attrs.get("description") or ""),
        head_sha=str(last.get("id") or ""),
        labels=_names(payload.get("labels"), "title"),
        draft=bool(attrs.get("draft") or attrs.get("work_in_progress")),
        title=str(attrs.get("title") or ""),
        reviewers=_names(payload.get("reviewers"), "username"),
        assignees=_names(payload.get("assignees"), "username"),
        newly_requested=_newly_requested(payload),
        delivery_id=delivery,
    )


def _newly_requested(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Usernames added as reviewer or assignee in a GitLab merge request update."""
    changes = _map(payload.get("changes"))
    added: list[str] = []
    for field in ("reviewers", "assignees"):
        change = _map(changes.get(field))
        before = {name.lower() for name in _names(change.get("previous"), "username")}
        for name in _names(change.get("current"), "username"):
            if name.lower() not in before:
                added.append(name.lower())
    return tuple(dict.fromkeys(added))


def _gitlab_note(payload: Mapping[str, Any], delivery: str) -> WebhookEvent | None:
    attrs = _map(payload.get("object_attributes"))
    noteable = str(attrs.get("noteable_type") or "")
    if noteable not in {"MergeRequest", "Issue"}:
        return None
    target = _map(
        payload.get("merge_request")
        if noteable == "MergeRequest"
        else payload.get("issue")
    )
    return WebhookEvent(
        provider="gitlab",
        kind="comment" if noteable == "MergeRequest" else "issue",
        action="created" if noteable == "MergeRequest" else "comment",
        project=_project_path(payload),
        number=int(target.get("iid") or 0),
        author=_username(payload.get("user")),
        body=str(attrs.get("note") or ""),
        head_sha=str(_map(target.get("last_commit")).get("id") or ""),
        labels=_names(target.get("labels"), "title"),
        draft=bool(target.get("draft") or target.get("work_in_progress")),
        title=str(target.get("title") or ""),
        assignees=_names(target.get("assignees"), "username"),
        delivery_id=delivery,
    )


def _gitlab_issue(payload: Mapping[str, Any], delivery: str) -> WebhookEvent:
    attrs = _map(payload.get("object_attributes"))
    return WebhookEvent(
        provider="gitlab",
        kind="issue",
        action=str(attrs.get("action") or ""),
        project=_project_path(payload),
        number=int(attrs.get("iid") or 0),
        author=_username(payload.get("user")),
        body=str(attrs.get("description") or ""),
        labels=_names(payload.get("labels"), "title"),
        title=str(attrs.get("title") or ""),
        assignees=_names(payload.get("assignees"), "username"),
        delivery_id=delivery,
    )


def _github_pull_request(payload: Mapping[str, Any], delivery: str) -> WebhookEvent:
    pull = _map(payload.get("pull_request"))
    head = _map(pull.get("head"))
    return WebhookEvent(
        provider="github",
        kind="change_request",
        action=str(payload.get("action") or ""),
        project=_repo_name(payload),
        number=int(pull.get("number") or 0),
        author=_login(payload.get("sender")),
        body=str(pull.get("body") or ""),
        head_sha=str(head.get("sha") or ""),
        labels=_names(pull.get("labels"), "name"),
        draft=bool(pull.get("draft")),
        title=str(pull.get("title") or ""),
        reviewers=_names(pull.get("requested_reviewers"), "login"),
        assignees=_names(pull.get("assignees"), "login"),
        delivery_id=delivery,
    )


def _github_comment(
    event: str, payload: Mapping[str, Any], delivery: str
) -> WebhookEvent | None:
    comment = _map(payload.get("comment"))
    if event == "issue_comment":
        issue = _map(payload.get("issue"))
        if "pull_request" not in issue:
            return WebhookEvent(
                provider="github",
                kind="issue",
                action="comment",
                project=_repo_name(payload),
                number=int(issue.get("number") or 0),
                author=_login(comment.get("user")),
                body=str(comment.get("body") or ""),
                labels=_names(issue.get("labels"), "name"),
                title=str(issue.get("title") or ""),
                assignees=_names(issue.get("assignees"), "login"),
                delivery_id=delivery,
            )
        pull = issue
    else:
        pull = _map(payload.get("pull_request"))
    return WebhookEvent(
        provider="github",
        kind="comment",
        action=str(payload.get("action") or "created"),
        project=_repo_name(payload),
        number=int(pull.get("number") or 0),
        author=_login(comment.get("user")),
        body=str(comment.get("body") or ""),
        head_sha=str(_map(pull.get("head")).get("sha") or ""),
        labels=_names(pull.get("labels"), "name"),
        draft=bool(pull.get("draft")),
        title=str(pull.get("title") or ""),
        assignees=_names(pull.get("assignees"), "login"),
        delivery_id=delivery,
    )


def _github_issue(payload: Mapping[str, Any], delivery: str) -> WebhookEvent:
    issue = _map(payload.get("issue"))
    assignee = _map(payload.get("assignee"))
    assignees = _names(issue.get("assignees"), "login")
    if assignee.get("login") and str(assignee["login"]).lower() not in _lower(
        assignees
    ):
        assignees = (*assignees, str(assignee["login"]))
    return WebhookEvent(
        provider="github",
        kind="issue",
        action=str(payload.get("action") or ""),
        project=_repo_name(payload),
        number=int(issue.get("number") or 0),
        author=_login(payload.get("sender")),
        body=str(issue.get("body") or ""),
        labels=_names(issue.get("labels"), "name"),
        title=str(issue.get("title") or ""),
        assignees=assignees,
        delivery_id=delivery,
    )


def _map(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _names(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        text = _map(item).get(key) if isinstance(item, Mapping) else item
        if isinstance(text, str) and text:
            names.append(text)
    return tuple(names)


def _username(value: object) -> str:
    return str(_map(value).get("username") or "")


def _login(value: object) -> str:
    return str(_map(value).get("login") or "")


def _project_path(payload: Mapping[str, Any]) -> str:
    return str(_map(payload.get("project")).get("path_with_namespace") or "")


def _repo_name(payload: Mapping[str, Any]) -> str:
    return str(_map(payload.get("repository")).get("full_name") or "")
