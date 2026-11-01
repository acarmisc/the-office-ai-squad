from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from code_squad._common.contract import Verdict
from code_squad.michael.gateway import MichaelWiring
from code_squad.server import create_app
from tests.agents.support import HEAD, NUMBER, PROJECT, writes_of
from tests.michael.support import (
    BOT,
    GITLAB_SECRET,
    ORG_YAML,
    WEBHOOK_SECRET,
    FakeSpecialists,
    no_model,
    result_for,
    webhook_client,
)

ALICE_OK = FakeSpecialists({"jim": result_for("jim"), "dwight": result_for("dwight")})


def _pull_request(
    *,
    action: str = "review_requested",
    sender: str = "dev-user",
    reviewers: tuple[str, ...] = (BOT,),
) -> dict[str, Any]:
    return {
        "action": action,
        "number": NUMBER,
        "pull_request": {
            "number": NUMBER,
            "title": "Show profile bio in ProfileCard",
            "body": "",
            "draft": False,
            "labels": [],
            "requested_reviewers": [{"login": name} for name in reviewers],
            "assignees": [],
            "head": {"sha": HEAD},
        },
        "repository": {"full_name": PROJECT},
        "sender": {"login": sender},
    }


def _issue_comment(body: str, author: str) -> dict[str, Any]:
    return {
        "action": "created",
        "issue": {
            "number": NUMBER,
            "title": "Show profile bio",
            "labels": [],
            "assignees": [],
            "pull_request": {"url": "https://api.github.com/x"},
        },
        "comment": {"body": body, "user": {"login": author}},
        "repository": {"full_name": PROJECT},
    }


def _post_github(
    client: TestClient,
    event: str,
    payload: dict[str, Any],
    *,
    delivery: str = "delivery-1",
    secret: str = WEBHOOK_SECRET,
) -> Any:
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": signature,
        },
    )


def _gitlab_note(body: str, author: str) -> dict[str, Any]:
    return {
        "object_kind": "note",
        "project": {"path_with_namespace": PROJECT},
        "user": {"username": author},
        "object_attributes": {"noteable_type": "MergeRequest", "note": body},
        "merge_request": {
            "iid": NUMBER,
            "title": "Show profile bio",
            "draft": False,
            "labels": [],
            "assignees": [],
            "last_commit": {"id": HEAD},
        },
    }


def _post_gitlab(
    client: TestClient, payload: dict[str, Any], *, token: str = GITLAB_SECRET
) -> Any:
    return client.post(
        "/webhooks/gitlab",
        json=payload,
        headers={"X-Gitlab-Token": token, "X-Gitlab-Event-UUID": "gl-1"},
    )


def _job(client: TestClient, response: Any) -> dict[str, Any]:
    job_id = response.json()["job_id"]
    body: dict[str, Any] = client.get(f"/jobs/{job_id}").json()
    return body


# ----- signatures and parsing ----------------------------------------------------


def test_github_bad_signature_is_401_and_nothing_runs(tmp_path: Path) -> None:
    specialists = FakeSpecialists({"jim": result_for("jim")})
    client, fake = webhook_client(tmp_path, specialists)
    response = _post_github(client, "pull_request", _pull_request(), secret="wrong")
    assert response.status_code == 401
    assert specialists.calls == []
    assert fake.writes == []


def test_gitlab_wrong_token_is_401(tmp_path: Path) -> None:
    client, _fake = webhook_client(tmp_path, FakeSpecialists())
    response = _post_gitlab(
        client, _gitlab_note("/squad review", "alice"), token="nope"
    )
    assert response.status_code == 401


def test_unsupported_event_is_ignored(tmp_path: Path) -> None:
    client, _fake = webhook_client(tmp_path, FakeSpecialists())
    response = _post_github(client, "push", {"ref": "refs/heads/main"})
    assert response.status_code == 202
    assert response.json() == {"status": "ignored", "reason": "unsupported event"}


def test_body_that_is_not_a_json_object_is_400(tmp_path: Path) -> None:
    client, _fake = webhook_client(tmp_path, FakeSpecialists())
    body = b"[1, 2]"
    signature = (
        "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    )
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": signature},
    )
    assert response.status_code == 400


# ----- trigger rules -------------------------------------------------------------


def test_review_request_is_accepted_and_the_job_publishes_once(tmp_path: Path) -> None:
    specialists = FakeSpecialists(
        {"jim": result_for("jim"), "dwight": result_for("dwight")}
    )
    client, fake = webhook_client(tmp_path, specialists)
    response = _post_github(client, "pull_request", _pull_request())
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"

    job = _job(client, response)
    assert job["state"] == "done"
    assert job["result"]["agent"] == "michael"
    assert job["result"]["verdict"] == Verdict.APPROVE.value
    assert sorted(specialists.agents()) == ["dwight", "jim"]
    assert all(call.payload["post"] is False for call in specialists.calls)
    statuses = writes_of(fake, "set_status")
    assert [item["context"] for item in statuses] == ["ai-review/michael"]
    assert statuses[0]["state"] == "success"


def test_duplicate_delivery_is_reported_as_duplicate(tmp_path: Path) -> None:
    client, _fake = webhook_client(tmp_path, ALICE_OK)
    first = _post_github(client, "pull_request", _pull_request(), delivery="same")
    second = _post_github(client, "pull_request", _pull_request(), delivery="same")
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate"}


def test_event_authored_by_the_bot_is_ignored(tmp_path: Path) -> None:
    client, _fake = webhook_client(tmp_path, FakeSpecialists())
    response = _post_github(client, "pull_request", _pull_request(sender=BOT))
    assert response.status_code == 202
    assert response.json()["reason"] == "event authored by the bot itself"


def test_comment_from_an_unauthorised_user_is_ignored(tmp_path: Path) -> None:
    specialists = FakeSpecialists()
    client, _fake = webhook_client(tmp_path, specialists)
    response = _post_github(
        client,
        "issue_comment",
        _issue_comment("/squad review", "mallory"),
        delivery="c1",
    )
    assert response.json() == {
        "status": "ignored",
        "reason": "commenter is not in allowed_commenters",
    }
    assert specialists.calls == []


def test_authorised_squad_command_is_accepted(tmp_path: Path) -> None:
    client, _fake = webhook_client(tmp_path, ALICE_OK)
    response = _post_github(
        client, "issue_comment", _issue_comment("/squad review", "alice"), delivery="c2"
    )
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"


def test_comment_without_a_mention_or_command_is_ignored(tmp_path: Path) -> None:
    client, _fake = webhook_client(tmp_path, ALICE_OK)
    response = _post_github(
        client, "issue_comment", _issue_comment("nice work", "alice"), delivery="c3"
    )
    assert response.json()["reason"] == "comment has no @mention or /squad command"


def test_repeated_trigger_for_the_same_change_and_head_is_debounced(
    tmp_path: Path,
) -> None:
    client, _fake = webhook_client(tmp_path, ALICE_OK)
    first = _post_github(
        client, "issue_comment", _issue_comment("/squad review", "alice"), delivery="d1"
    )
    second = _post_github(
        client, "issue_comment", _issue_comment("/squad review", "alice"), delivery="d2"
    )
    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "ignored"
    assert second.json()["reason"].startswith("debounced")


def test_draft_change_request_is_skipped(tmp_path: Path) -> None:
    client, _fake = webhook_client(tmp_path, FakeSpecialists())
    payload = _pull_request()
    payload["pull_request"]["draft"] = True
    response = _post_github(client, "pull_request", payload)
    assert response.json()["reason"] == "draft change request is skipped"


def test_gitlab_note_from_an_authorised_user_is_accepted_and_reviewed(
    tmp_path: Path,
) -> None:
    specialists = FakeSpecialists(
        {"jim": result_for("jim"), "dwight": result_for("dwight")}
    )
    client, fake = webhook_client(tmp_path, specialists)
    response = _post_gitlab(client, _gitlab_note("/squad review", "alice"))
    assert response.status_code == 202
    job = _job(client, response)
    assert job["state"] == "done"
    assert sorted(specialists.agents()) == ["dwight", "jim"]
    assert [item["state"] for item in writes_of(fake, "set_status")] == ["success"]


def test_missing_bot_identity_ignores_everything(tmp_path: Path) -> None:
    org = "trigger:\n  allowed_commenters: [alice]\n"
    client, _fake = webhook_client(tmp_path, FakeSpecialists(), org=org)
    response = _post_github(client, "pull_request", _pull_request())
    assert response.json() == {
        "status": "ignored",
        "reason": "vcs.bot_username is not configured for this project",
    }


# ----- route registration and invocation ------------------------------------------


def test_webhook_routes_are_absent_unless_enabled_by_env(tmp_path: Path) -> None:
    client, _fake = webhook_client(tmp_path, FakeSpecialists(), providers="")
    assert _post_github(client, "pull_request", _pull_request()).status_code == 404


def test_webhook_routes_exist_only_for_michael(tmp_path: Path) -> None:
    wiring = MichaelWiring(env={"WEBHOOK_PROVIDERS": "github"})
    app = create_app("jim", model_factory=no_model, wiring=wiring)
    response = TestClient(app).post("/webhooks/github", json={})
    assert response.status_code == 404


def test_invocations_on_michael_go_through_the_orchestrator(tmp_path: Path) -> None:
    specialists = FakeSpecialists(
        {"jim": result_for("jim"), "dwight": result_for("dwight")}
    )
    client, fake = webhook_client(tmp_path, specialists, providers="")
    response = client.post(
        "/invocations",
        json={
            "prompt": "Review the change.",
            "project": PROJECT,
            "target": str(NUMBER),
            "mode": "review",
            "post": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agent"] == "michael"
    assert body["data"]["intent"] == "mr_review"
    assert body["data"]["risk"]["tier"] == "low"
    assert sorted(specialists.agents()) == ["dwight", "jim"]
    assert fake.writes == []
    assert "dry-run blocked 1 external write attempt(s)" in body["warnings"]


def test_invocations_on_michael_with_respond_async_completes(tmp_path: Path) -> None:
    specialists = FakeSpecialists(
        {"jim": result_for("jim"), "dwight": result_for("dwight")}
    )
    client, _fake = webhook_client(tmp_path, specialists, providers="")
    accepted = client.post(
        "/invocations",
        json={
            "prompt": "Review.",
            "project": PROJECT,
            "target": str(NUMBER),
            "post": False,
        },
        headers={"Prefer": "respond-async"},
    )
    assert accepted.status_code == 202
    job = _job(client, accepted)
    assert job["state"] == "done"
    assert job["result"]["agent"] == "michael"


# ----- delivery redelivery after refusals -------------------------------------------


def test_delivery_refused_by_invalid_config_is_processed_on_redelivery(
    tmp_path: Path,
) -> None:
    invalid = f"vcs:\n  bot_username: {BOT}\ntrigger:\n  events: [not_an_event]\n"
    specialists = FakeSpecialists(
        {"jim": result_for("jim"), "dwight": result_for("dwight")}
    )
    client, _fake = webhook_client(tmp_path, specialists, org=invalid)
    refused = _post_github(client, "pull_request", _pull_request(), delivery="retry-1")
    assert refused.status_code == 503
    assert specialists.calls == []

    (tmp_path / "squad.yaml").write_text(ORG_YAML, encoding="utf-8")
    redelivered = _post_github(
        client, "pull_request", _pull_request(), delivery="retry-1"
    )
    assert redelivered.status_code == 202
    assert _job(client, redelivered)["state"] == "done"
    assert sorted(specialists.agents()) == ["dwight", "jim"]


def test_delivery_rejected_by_signature_is_processed_on_redelivery(
    tmp_path: Path,
) -> None:
    specialists = FakeSpecialists({"jim": result_for("jim")})
    client, _fake = webhook_client(tmp_path, specialists)
    bad = _post_github(
        client, "pull_request", _pull_request(), delivery="sig-1", secret="wrong"
    )
    assert bad.status_code == 401
    good = _post_github(client, "pull_request", _pull_request(), delivery="sig-1")
    assert good.status_code == 202


def test_unreadable_payload_is_400_and_processed_on_redelivery(tmp_path: Path) -> None:
    client, _fake = webhook_client(tmp_path, ALICE_OK)
    broken = _pull_request()
    broken["pull_request"]["number"] = "not-a-number"
    refused = _post_github(client, "pull_request", broken, delivery="parse-1")
    assert refused.status_code == 400
    fixed = _post_github(client, "pull_request", _pull_request(), delivery="parse-1")
    assert fixed.status_code == 202


def test_deliberately_ignored_delivery_is_reported_as_duplicate(tmp_path: Path) -> None:
    client, _fake = webhook_client(tmp_path, FakeSpecialists())
    first = _post_github(
        client,
        "issue_comment",
        _issue_comment("/squad review", "mallory"),
        delivery="ignored-1",
    )
    second = _post_github(
        client,
        "issue_comment",
        _issue_comment("/squad review", "mallory"),
        delivery="ignored-1",
    )
    assert first.json()["status"] == "ignored"
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate"}


def test_trigger_events_setting_is_enforced_by_the_gateway(tmp_path: Path) -> None:
    org = (
        f"vcs:\n  bot_username: {BOT}\n"
        "trigger:\n  allowed_commenters: [alice]\n  events: [review_requested]\n"
    )
    client, _fake = webhook_client(tmp_path, ALICE_OK, org=org)
    response = _post_github(
        client, "issue_comment", _issue_comment("/squad review", "alice"), delivery="e1"
    )
    assert response.json() == {
        "status": "ignored",
        "reason": "event not enabled in trigger.events",
    }
