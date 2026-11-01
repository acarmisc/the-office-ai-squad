"""The VCS protocol has no merge operation (brief section 18, ADR 0011)."""

from __future__ import annotations

from code_squad._common.vcs.base import Capability, VcsProvider
from code_squad._common.vcs.fake import FakeVcsProvider
from code_squad._common.vcs.github import GitHubProvider
from code_squad._common.vcs.gitlab import GitLabProvider


def _public_names(cls: type) -> set[str]:
    return {name for name in dir(cls) if not name.startswith("_")}


def test_protocol_has_no_merge_operation() -> None:
    assert not [name for name in _public_names(VcsProvider) if "merge" in name]


def test_no_provider_exposes_a_merge_operation() -> None:
    for cls in (GitLabProvider, GitHubProvider, FakeVcsProvider):
        assert not [name for name in _public_names(cls) if "merge" in name], cls


def test_no_capability_names_a_merge() -> None:
    assert not [member for member in Capability if "merge" in member.value]
