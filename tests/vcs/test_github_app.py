from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache

import httpx
import jwt
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from code_squad._common.vcs.base import Capability, StatusState
from code_squad._common.vcs.github import AppAuth, GitHubProvider
from code_squad._common.vcs.http import HttpClient

API = "https://api.github.com"
REPO = "acme/web"
NOW = 1_800_000_000.0


@lru_cache(maxsize=1)
def _keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode("ascii")
    )
    return private, public


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _expiry_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _app(
    clock: Clock, http: HttpClient | None = None, installation: int | None = 555
) -> AppAuth:
    private, _public = _keypair()
    return AppAuth(
        "12345",
        private,
        installation,
        http=http or HttpClient(sleep=lambda _s: None),
        clock=clock,
    )


def test_app_jwt_is_rs256_with_app_id_issuer_and_short_lifetime() -> None:
    clock = Clock(NOW)
    auth = _app(clock)
    token = auth.identity_headers()["Authorization"].removeprefix("Bearer ")
    _private, public = _keypair()
    claims = jwt.decode(
        token,
        public,
        algorithms=["RS256"],
        options={"verify_iat": False, "verify_exp": False},
    )
    assert claims["iss"] == "12345"
    assert claims["iat"] == int(NOW) - 60
    assert claims["exp"] == int(NOW) + 540
    assert jwt.get_unverified_header(token)["alg"] == "RS256"


def test_installation_token_request_is_scoped_to_the_repository() -> None:
    clock = Clock(NOW)
    auth = _app(clock)
    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(f"{API}/app/installations/555/access_tokens").mock(
            return_value=httpx.Response(
                201,
                json={
                    "token": "ghs_fake_installation",
                    "expires_at": _expiry_iso(NOW + 3600),
                },
            )
        )
        assert auth.token_for(REPO) == "ghs_fake_installation"
    body = json.loads(route.calls.last.request.content)
    assert body == {"repositories": ["web"]}


def test_installation_token_is_cached_then_refreshed_five_minutes_before_expiry() -> (
    None
):
    clock = Clock(NOW)
    auth = _app(clock)
    tokens = iter(["ghs_first", "ghs_second"])
    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(f"{API}/app/installations/555/access_tokens").mock(
            side_effect=lambda _request: httpx.Response(
                201, json={"token": next(tokens), "expires_at": _expiry_iso(NOW + 3600)}
            )
        )
        assert auth.token_for(REPO) == "ghs_first"
        clock.now = NOW + 3600 - 301
        assert auth.token_for(REPO) == "ghs_first"
        assert route.call_count == 1
        clock.now = NOW + 3600 - 299
        assert auth.token_for(REPO) == "ghs_second"
        assert route.call_count == 2


def test_installation_id_is_discovered_when_not_configured() -> None:
    clock = Clock(NOW)
    auth = _app(clock, installation=None)
    with respx.mock(assert_all_mocked=True) as router:
        lookup = router.get(f"{API}/repos/acme/web/installation").mock(
            return_value=httpx.Response(200, json={"id": 777})
        )
        router.get(f"{API}/repos/acme/other/installation").mock(
            return_value=httpx.Response(200, json={"id": 777})
        )
        router.post(f"{API}/app/installations/777/access_tokens").mock(
            return_value=httpx.Response(
                201, json={"token": "ghs_x", "expires_at": _expiry_iso(NOW + 3600)}
            )
        )
        assert auth.token_for(REPO) == "ghs_x"
        assert auth.token_for("acme/other") == "ghs_x"
    assert lookup.call_count == 1


def test_app_provider_reports_check_runs_and_bot_identity() -> None:
    clock = Clock(NOW)
    auth = _app(clock)
    provider = GitHubProvider(auth=auth, http=HttpClient(sleep=lambda _s: None))
    assert Capability.CHECK_RUNS in provider.capabilities
    with respx.mock(assert_all_mocked=True) as router:
        router.get(f"{API}/app").mock(
            return_value=httpx.Response(200, json={"id": 12345, "slug": "code-squad"})
        )
        who = provider.whoami()
    assert who.username == "code-squad[bot]"


def test_app_provider_publishes_status_as_check_run_with_repo_token() -> None:
    clock = Clock(NOW)
    auth = _app(clock)
    provider = GitHubProvider(auth=auth, http=HttpClient(sleep=lambda _s: None))
    sha = "a" * 40
    with respx.mock(assert_all_mocked=True) as router:
        router.post(f"{API}/app/installations/555/access_tokens").mock(
            return_value=httpx.Response(
                201, json={"token": "ghs_repo", "expires_at": _expiry_iso(NOW + 3600)}
            )
        )
        check = router.post(f"{API}/repos/acme/web/check-runs").mock(
            return_value=httpx.Response(201, json={"id": 9001})
        )
        status_id = provider.set_status(
            REPO, sha, StatusState.FAILED, "ai-review/jim", "blocker found", ""
        )
    assert status_id == "9001"
    sent = json.loads(check.calls.last.request.content)
    assert sent["conclusion"] == "failure" and sent["status"] == "completed"
    assert check.calls.last.request.headers["Authorization"] == "Bearer ghs_repo"


def test_pat_provider_falls_back_to_commit_status() -> None:
    from code_squad._common.vcs.github import TokenAuth

    provider = GitHubProvider(
        auth=TokenAuth("fake-token-for-tests"), http=HttpClient(sleep=lambda _s: None)
    )
    assert Capability.CHECK_RUNS not in provider.capabilities
    with respx.mock(assert_all_mocked=True) as router:
        status = router.post(f"{API}/repos/acme/web/statuses/{'a' * 40}").mock(
            return_value=httpx.Response(201, json={"id": 8001})
        )
        assert (
            provider.set_status(
                REPO, "a" * 40, StatusState.PENDING, "ai-review/jim", "", ""
            )
            == "8001"
        )
    assert json.loads(status.calls.last.request.content)["state"] == "pending"
