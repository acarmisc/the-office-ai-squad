from __future__ import annotations

import re
from typing import Final

from code_squad._common.vcs.base import Issue, VcsError, VcsProvider

_KEY: Final = re.compile(r"^(?P<project>[^#\s]+)#(?P<number>\d+)$")


class VcsIssueTracker:
    """Issue adapter over a VCS provider. Keys look like ``group/repo#12``."""

    def __init__(self, provider: VcsProvider) -> None:
        self._provider = provider
        self.name = provider.name

    def get_issue(self, key: str) -> Issue:
        project, number = parse_key(key)
        return self._provider.get_issue(project, number)

    def comment_on_issue(self, key: str, body: str) -> str:
        project, number = parse_key(key)
        return self._provider.comment_on_issue(project, number, body)


def parse_key(key: str) -> tuple[str, int]:
    match = _KEY.match(key)
    if match is None:
        raise VcsError("issue key must look like 'group/repo#number'")
    return match.group("project"), int(match.group("number"))
