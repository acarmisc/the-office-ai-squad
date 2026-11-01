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
    "k8s_get": ToolClass.READ,
    "k8s_describe": ToolClass.READ,
    "k8s_events": ToolClass.READ,
    "k8s_logs": ToolClass.READ,
    "k8s_top": ToolClass.READ,
    "rollout_history": ToolClass.READ,
    "ci_runs": ToolClass.READ,
    "ci_job_log": ToolClass.READ,
    "prom_query": ToolClass.READ,
    "logs_query": ToolClass.READ,
    "deployment_status": ToolClass.READ,
    "recent_changes": ToolClass.READ,
    "get_task": ToolClass.READ,
    "sandbox_read": ToolClass.READ,
    "sandbox_list": ToolClass.READ,
    "sandbox_diff": ToolClass.READ,
    "start_work": ToolClass.LOCAL_MUTATION,
    "write_file": ToolClass.LOCAL_MUTATION,
    "apply_patch": ToolClass.LOCAL_MUTATION,
    "run_command": ToolClass.LOCAL_MUTATION,
    "run_checks": ToolClass.LOCAL_MUTATION,
    "commit": ToolClass.LOCAL_MUTATION,
    "push_branch": ToolClass.EXTERNAL_WRITE,
    "open_change_request": ToolClass.EXTERNAL_WRITE,
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
