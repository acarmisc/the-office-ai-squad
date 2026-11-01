from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Final


class ToolClass(StrEnum):
    READ = "read"
    LOCAL_MUTATION = "local_mutation"
    EXTERNAL_WRITE = "external_write"


class UnclassifiedToolError(KeyError):
    pass


TOOL_POLICY: dict[str, ToolClass] = {
    "finish": ToolClass.READ,
    "read_knowledge": ToolClass.READ,
    "load_skill": ToolClass.READ,
    "get_project_skills": ToolClass.READ,
    "get_review_context": ToolClass.READ,
    "read_file": ToolClass.READ,
    "search_repo": ToolClass.READ,
    "list_tree": ToolClass.READ,
    "publish_review": ToolClass.EXTERNAL_WRITE,
    "parse_dependencies": ToolClass.READ,
    "lookup_vulnerabilities": ToolClass.READ,
    "lookup_cve": ToolClass.READ,
    "search_advisories": ToolClass.READ,
}

_NAME_ATTR: Final = "tool_name"


def classify(name: str) -> ToolClass:
    try:
        return TOOL_POLICY[name]
    except KeyError as exc:
        raise UnclassifiedToolError(name) from exc


def tool_name(tool: object) -> str:
    name = getattr(tool, _NAME_ATTR, None)
    if isinstance(name, str):
        return name
    fallback = getattr(tool, "__name__", None)
    if isinstance(fallback, str):
        return fallback
    raise TypeError(f"cannot determine tool name for {tool!r}")


def unclassified(tools: Iterable[object]) -> list[str]:
    names = [tool_name(tool) for tool in tools]
    return [name for name in names if name not in TOOL_POLICY]
