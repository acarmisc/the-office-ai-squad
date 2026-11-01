from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import respx

from code_squad._common.vcs.base import VcsProvider
from code_squad._common.vcs.conformance.scenario import seed_fake
from code_squad._common.vcs.conformance.suite import ALL_CHECKS, Check
from code_squad._common.vcs.fake import FAKE_TOKEN, FakeVcsProvider
from code_squad._common.vcs.github import GitHubProvider, TokenAuth
from code_squad._common.vcs.gitlab import GitLabProvider
from code_squad._common.vcs.http import HttpClient
from tests.vcs.recorded import GITLAB_BASE, github_recorder, gitlab_recorder

BACKENDS = ("fake", "gitlab", "github")


def _no_sleep(_seconds: float) -> None:
    return None


@contextmanager
def backend(name: str) -> Iterator[VcsProvider]:
    if name == "fake":
        fake = FakeVcsProvider()
        seed_fake(fake)
        yield fake
        return
    recorder = gitlab_recorder() if name == "gitlab" else github_recorder()
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        router.route().mock(side_effect=recorder)
        http = HttpClient(sleep=_no_sleep)
        if name == "gitlab":
            yield GitLabProvider(GITLAB_BASE, FAKE_TOKEN, http)
        else:
            yield GitHubProvider(auth=TokenAuth(FAKE_TOKEN), http=http)


@pytest.mark.parametrize("backend_name", BACKENDS)
@pytest.mark.parametrize("check", ALL_CHECKS, ids=lambda fn: fn.__name__)
def test_provider_conformance(backend_name: str, check: Check) -> None:
    with backend(backend_name) as provider:
        check(provider)


@pytest.mark.parametrize("backend_name", BACKENDS)
def test_every_backend_declares_the_same_core_surface(backend_name: str) -> None:
    with backend(backend_name) as provider:
        assert provider.name in {"fake", "gitlab", "github"}
        assert isinstance(provider.capabilities, frozenset)
