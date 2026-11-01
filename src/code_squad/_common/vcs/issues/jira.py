from __future__ import annotations

import base64
import re
from typing import Any, Final

from code_squad._common.vcs.base import (
    CapabilityError,
    Issue,
    VcsError,
)
from code_squad._common.vcs.http import HttpClient, as_dict, as_list

_KEY: Final = re.compile(r"^(?P<project>[A-Z][A-Z0-9_]+)-(?P<number>\d+)$")


class JiraIssueTracker:
    """Read-only Jira adapter. Commenting raises CapabilityError."""

    name: str = "jira"

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        http: HttpClient | None = None,
    ) -> None:
        self._root = base_url.rstrip("/")
        self._http = http or HttpClient(provider="jira")
        raw = f"{email}:{api_token}".encode()
        self._headers = {
            "Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}",
            "Accept": "application/json",
        }

    def get_issue(self, key: str) -> Issue:
        match = _KEY.match(key)
        if match is None:
            raise VcsError("Jira key must look like 'PROJ-123'")
        data = as_dict(
            self._http.get_json(
                f"{self._root}/rest/api/3/issue/{key}", headers=self._headers
            )
        )
        fields = as_dict(data.get("fields") or {})
        return Issue(
            project=match.group("project"),
            number=int(match.group("number")),
            title=str(fields.get("summary") or ""),
            body=adf_to_text(fields.get("description")),
            labels=tuple(str(label) for label in as_list(fields.get("labels") or [])),
            assignees=_assignee(fields),
            state=str(as_dict(fields.get("status") or {}).get("name") or ""),
            web_url=f"{self._root}/browse/{key}",
        )

    def comment_on_issue(self, key: str, body: str) -> str:
        raise CapabilityError("the Jira adapter is read-only")


def adf_to_text(node: object) -> str:
    """Flatten an Atlassian Document Format tree into plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(item) for item in node)
    if not isinstance(node, dict):
        return ""
    data: dict[str, Any] = node
    if data.get("type") == "text":
        return str(data.get("text") or "")
    children = adf_to_text(data.get("content"))
    if data.get("type") in {"paragraph", "heading", "listItem", "codeBlock"}:
        return children + "\n"
    return children


def _assignee(fields: dict[str, Any]) -> tuple[str, ...]:
    assignee = fields.get("assignee")
    if not isinstance(assignee, dict):
        return ()
    return (str(assignee.get("displayName") or ""),)
