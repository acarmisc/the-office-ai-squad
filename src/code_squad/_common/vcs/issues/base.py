from __future__ import annotations

from typing import Protocol

from code_squad._common.vcs.base import Issue


class IssueTracker(Protocol):
    name: str

    def get_issue(self, key: str) -> Issue: ...

    def comment_on_issue(self, key: str, body: str) -> str: ...
