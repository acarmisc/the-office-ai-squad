from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from code_squad._common.vcs.base import VcsProvider
from code_squad._common.vcs.github import (
    DEFAULT_BASE_URL,
    AppAuth,
    GitHubProvider,
    TokenAuth,
)
from code_squad._common.vcs.gitlab import GitLabProvider
from code_squad._common.vcs.http import HttpClient


@dataclass(frozen=True)
class VcsSettings:
    provider: Literal["gitlab", "github", "auto"]
    base_url: str
    token: str | None = None
    app_id: str | None = None
    app_private_key: str | None = None
    installation_id: int | None = None


def resolve_kind(settings: VcsSettings) -> Literal["gitlab", "github"]:
    if settings.provider != "auto":
        return settings.provider
    return "github" if "github" in urlsplit(settings.base_url).netloc else "gitlab"


def build_provider(
    settings: VcsSettings, http: HttpClient | None = None
) -> VcsProvider:
    if resolve_kind(settings) == "gitlab":
        return GitLabProvider(settings.base_url, _require_token(settings), http)
    return GitHubProvider(
        settings.base_url or DEFAULT_BASE_URL,
        auth=_github_auth(settings, http),
        http=http,
    )


def _github_auth(settings: VcsSettings, http: HttpClient | None) -> TokenAuth | AppAuth:
    if settings.app_id and settings.app_private_key:
        return AppAuth(
            settings.app_id,
            settings.app_private_key,
            settings.installation_id,
            http=http,
            base_url=settings.base_url or DEFAULT_BASE_URL,
        )
    return TokenAuth(_require_token(settings))


def _require_token(settings: VcsSettings) -> str:
    if not settings.token:
        raise ValueError("a VCS token or secret is required for this provider")
    return settings.token
