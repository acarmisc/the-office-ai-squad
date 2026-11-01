from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from code_squad._common.vcs.base import CapabilityError, VcsError
from code_squad._common.vcs.factory import VcsSettings, build_provider, resolve_kind
from code_squad._common.vcs.github import AppAuth, GitHubProvider, TokenAuth
from code_squad._common.vcs.gitlab import GitLabProvider
from code_squad._common.vcs.http import HttpClient
from code_squad._common.vcs.issues import JiraIssueTracker, VcsIssueTracker
from code_squad._common.vcs.issues.jira import adf_to_text
from code_squad._common.vcs.issues.vcs_tracker import parse_key


def test_auto_infers_github_from_host_and_gitlab_otherwise() -> None:
    assert (
        resolve_kind(VcsSettings("auto", "https://github.com", token="t")) == "github"
    )
    assert (
        resolve_kind(
            VcsSettings("auto", "https://github.example.test/api/v3", token="t")
        )
        == "github"
    )
    assert (
        resolve_kind(VcsSettings("auto", "https://ghe.example.test/api/v3", token="t"))
        == "gitlab"
    )
    assert (
        resolve_kind(VcsSettings("auto", "https://gitlab.example.com", token="t"))
        == "gitlab"
    )
    assert (
        resolve_kind(VcsSettings("github", "https://gitlab.example.com", token="t"))
        == "github"
    )


def test_build_gitlab_and_pat_github_providers() -> None:
    gitlab = build_provider(VcsSettings("gitlab", "https://gitlab.test", token="t"))
    assert isinstance(gitlab, GitLabProvider)
    github = build_provider(VcsSettings("github", "https://api.github.com", token="t"))
    assert isinstance(github, GitHubProvider)
    assert isinstance(github._auth, TokenAuth)


def test_github_app_is_used_when_app_fields_are_present() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    provider = build_provider(
        VcsSettings(
            "github",
            "https://api.github.com",
            app_id="1",
            app_private_key=pem,
            installation_id=9,
        )
    )
    assert isinstance(provider, GitHubProvider)
    assert isinstance(provider.auth, AppAuth)


def test_missing_token_fails_without_echoing_anything() -> None:
    with pytest.raises(ValueError, match="token"):
        build_provider(VcsSettings("gitlab", "https://gitlab.test"))


def test_vcs_issue_key_parsing() -> None:
    assert parse_key("acme/web#12") == ("acme/web", 12)
    with pytest.raises(VcsError):
        parse_key("acme/web-12")


def test_vcs_issue_tracker_delegates_to_provider() -> None:
    from tests.vcs.recorded import GITLAB_BASE, gitlab_recorder, serve

    provider = GitLabProvider(GITLAB_BASE, "t", HttpClient(sleep=lambda _s: None))
    with serve(gitlab_recorder()):
        tracker = VcsIssueTracker(provider)
        issue = tracker.get_issue("acme/web#12")
        assert issue.title == "Greeting broken"
        assert tracker.comment_on_issue("acme/web#12", "hi") == "905"


def test_adf_is_flattened_to_plain_text() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Button"},
                    {"type": "text", "text": " broken"},
                ],
            },
            {"type": "codeBlock", "content": [{"type": "text", "text": "npm test"}]},
        ],
    }
    assert adf_to_text(document) == "Button broken\nnpm test\n"
    assert adf_to_text(None) == ""


def test_jira_reads_issue_with_basic_auth_and_is_read_only() -> None:
    payload = {
        "fields": {
            "summary": "Login fails",
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "On Safari"}],
                    }
                ],
            },
            "labels": ["auth"],
            "assignee": {"displayName": "Dana"},
            "status": {"name": "In Progress"},
        }
    }
    with respx.mock(assert_all_mocked=True) as router:
        route = router.get("https://jira.test/rest/api/3/issue/SEC-7").mock(
            return_value=httpx.Response(200, json=payload)
        )
        tracker = JiraIssueTracker(
            "https://jira.test",
            "bot@example.test",
            "fake-token-for-tests",
            HttpClient(sleep=lambda _s: None),
        )
        issue = tracker.get_issue("SEC-7")
        with pytest.raises(CapabilityError):
            tracker.comment_on_issue("SEC-7", "nope")
    assert (issue.project, issue.number, issue.title) == ("SEC", 7, "Login fails")
    assert issue.body == "On Safari\n"
    assert issue.assignees == ("Dana",)
    assert issue.state == "In Progress"
    expected = base64.b64encode(b"bot@example.test:fake-token-for-tests").decode()
    assert route.calls.last.request.headers["Authorization"] == f"Basic {expected}"
    assert json.dumps(payload)


def test_jira_rejects_malformed_keys() -> None:
    tracker = JiraIssueTracker("https://jira.test", "a", "b")
    with pytest.raises(VcsError):
        tracker.get_issue("not a key")
