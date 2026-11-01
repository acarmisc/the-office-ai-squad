"""Generate the reference pages under docs/reference/ from the code.

Pages: configuration (every schema section and field), environment (bootstrap
variables), tool-policy (tool, class and agents), vcs-capabilities (capability
matrix) and agents (defaults per agent). ``--check`` writes nothing and exits 1
when a committed page differs from what the code produces.

The output is deterministic: process environment overrides that change agent
defaults are removed before rendering.
"""

from __future__ import annotations

import json
import os
import sys
import types
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Union, cast, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from code_squad._common.config.bootstrap import (
    NESTING_NOTE,
    render_env_table,
)
from code_squad._common.config.meta import field_meta
from code_squad._common.config.schema import (
    Baseline,
    ProjectsFile,
    RepoConfig,
    SquadFields,
)
from code_squad._common.registry import all_specs
from code_squad._common.spec import AgentSpec
from code_squad._common.tool_policy import TOOL_POLICY, ToolClass, classify, tool_name
from code_squad._common.vcs.base import Capability
from code_squad._common.vcs.github import AppAuth, GitHubProvider, TokenAuth
from code_squad._common.vcs.gitlab import GitLabProvider

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
REFERENCE_DIR: Final[Path] = ROOT / "docs" / "reference"
MARKER: Final = (
    "<!-- generated — do not edit. Source: scripts/gen_docs.py. "
    "Regenerate with: just docs-gen -->"
)
_AGENT_OVERRIDE_VARS: Final[tuple[str, ...]] = (
    "AGENT_MODEL_ID",
    "AGENT_MAX_TOKENS",
    "AGENT_MAX_ITERATIONS",
    "AGENT_TEMPERATURE",
    "AGENT_PROMPT_FILE",
    "EGRESS_PROXY_URL",
)
_DEFAULT_JSON_CHARS: Final = 120
_CONFIG_ANCHOR: Final = "Organisation and repository keys"

# Variables read by the code that are not in BOOTSTRAP_ENV. TODO(architect): move
# them into bootstrap.BOOTSTRAP_ENV so they reach .env.example and this page.
_UNLISTED_VARIABLES: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "WEBHOOK_PROVIDERS",
        "Comma-separated providers whose webhook route is registered on michael: "
        "gitlab, github. Unset means no /webhooks route exists.",
        "-",
    ),
    (
        "WEBHOOK_SECRETS_DIR",
        "Directory holding gitlab-webhook-secret and github-webhook-secret. Unset "
        "means "
        "the secret provider is used.",
        "-",
    ),
    (
        "POD_NAMESPACE",
        "Namespace used for specialist service DNS names when no URL is configured.",
        "default",
    ),
    (
        "SANDBOX_NAMESPACE",
        "Selects the Kubernetes sandbox for pam when set. When unset, pam uses the "
        "local process sandbox, which is for development only.",
        "-",
    ),
    (
        "SANDBOX_IMAGE",
        "Sandbox pod image. Required when SANDBOX_NAMESPACE is set.",
        "-",
    ),
    (
        "SANDBOX_ACTIVE_DEADLINE_SECONDS",
        "Hard wall-clock limit of a sandbox pod.",
        "1800",
    ),
    (
        "SANDBOX_TTL_SECONDS_AFTER_FINISHED",
        "Stored on the sandbox backend but not applied: pods carry no TTL field.",
        "300",
    ),
    (
        "SANDBOX_RESOURCES_JSON",
        "JSON object with requests and limits for each sandbox pod.",
        '{"requests": {"cpu": "250m", "memory": "512Mi"}, "limits": {"cpu": "2", '
        '"memory": "2Gi"}}',
    ),
    (
        "MICHAEL_LLM_INTENT",
        "Opt-in: a small model classifies requests that the rules cannot classify.",
        "off",
    ),
    (
        "MICHAEL_LLM_SUMMARY",
        "Opt-in: a model writes a neutral narrative above the deterministic summary.",
        "off",
    ),
    (
        "MICHAEL_SUMMARY_MODEL",
        "Model alias for the optional summary narrative.",
        "sonnet-5-5",
    ),
    (
        "LOG_LEVEL",
        "Log level of the process. Read directly; config observability.log_level is "
        "not "
        "applied.",
        "INFO",
    ),
    (
        "SQUAD_SECRET_<NAME>",
        "Secret values for the env secret provider (development and tests only).",
        "-",
    ),
    (
        "JIRA_BASE_URL",
        "Jira base URL. When set and the jira-api-token secret is available, pam reads "
        "task text from Jira (read only) instead of the VCS issue tracker.",
        "-",
    ),
    (
        "KUBERNETES_SERVICE_HOST",
        "Set by Kubernetes. darryl uses it to detect in-cluster configuration.",
        "-",
    ),
)

_CAPABILITY_FALLBACKS: Final[dict[Capability, str]] = {
    Capability.CHECK_RUNS: (
        "Without a GitHub App, verdicts are published as commit statuses and michael "
        "adds the warning 'check runs unavailable; used commit status'."
    ),
    Capability.COMMIT_STATUS: (
        "Verdicts use the commit status context ai-review/<agent>. Check runs are "
        "preferred on GitHub App authentication."
    ),
    Capability.BATCHED_REVIEW: (
        "GitLab has no batched review. Inline comments are posted as discussions."
    ),
    Capability.APPROVE: (
        "A formal approval is submitted only when vcs.approve_mode allows it. A "
        "provider that refuses it adds the warning 'formal review is not supported by "
        "this provider'."
    ),
    Capability.DRAFT_CHANGE_REQUEST: (
        "pam opens a draft only when implementer.mr_draft is true."
    ),
    Capability.RESOLVE_THREAD: (
        "Not used by the publication path. GitHub raises CapabilityError because "
        "resolving threads needs GraphQL, which is not implemented."
    ),
    Capability.CI_LOGS: (
        "darryl trims job logs to the failure region before the model reads them."
    ),
    Capability.ISSUES: (
        "Issue reads and comments use the same provider. Jira is a separate, read-only "
        "tracker used for task text."
    ),
    Capability.PUSH: (
        "pam pushes over HTTPS with the provider credentials. Without this capability "
        "an implementation run cannot publish its branch."
    ),
}

_TYPE_NAMES: Final[dict[type, str]] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}
_BOUND_LABELS: Final[dict[str, str]] = {
    "ge": ">=",
    "gt": ">",
    "le": "<=",
    "lt": "<",
    "min_length": "min length",
    "max_length": "max length",
    "pattern": "pattern",
}


@dataclass(frozen=True)
class _Node:
    path: str
    model: type[BaseModel]


def _clean_environment() -> None:
    for name in _AGENT_OVERRIDE_VARS:
        os.environ.pop(name, None)


def _code(text: str) -> str:
    return f"`{text}`"


def _cell(text: str) -> str:
    escaped = text.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
    return escaped.replace("\n", " ")


def _json_text(value: object) -> str:
    text = json.dumps(value, sort_keys=True, default=str)
    if len(text) > _DEFAULT_JSON_CHARS:
        text = text[: _DEFAULT_JSON_CHARS - 3] + "..."
    return _code(text)


def _unwrap_annotated(annotation: Any) -> Any:
    if get_origin(annotation) is Annotated:
        return get_args(annotation)[0]
    return annotation


def _split_optional(annotation: Any) -> tuple[Any, bool]:
    annotation = _unwrap_annotated(annotation)
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = get_args(annotation)
        if type(None) in args:
            rest = [arg for arg in args if arg is not type(None)]
            if len(rest) == 1:
                return rest[0], True
    return annotation, False


def _type_text(annotation: Any) -> str:
    inner, optional = _split_optional(annotation)
    text = _type_core(inner)
    return f"{text} or null" if optional else text


def _type_core(annotation: Any) -> str:
    annotation = _unwrap_annotated(annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        return "one of " + ", ".join(_code(str(value)) for value in args)
    if origin is list:
        return f"list of {_type_text(args[0])}" if args else "list"
    if origin is dict:
        if len(args) == 2:
            return f"map of {_type_text(args[0])} to {_type_text(args[1])}"
        return "map"
    if isinstance(annotation, type):
        if issubclass(annotation, Enum):
            return "one of " + ", ".join(_code(str(m.value)) for m in annotation)
        if issubclass(annotation, BaseModel):
            return f"object ({annotation.__name__})"
        if annotation.__name__ == "date":
            return "date (YYYY-MM-DD)"
        return _TYPE_NAMES.get(annotation, annotation.__name__)
    return str(annotation)


def _constraints(info: FieldInfo) -> str:
    parts: list[str] = []
    for meta in info.metadata:
        for attr, label in _BOUND_LABELS.items():
            value = getattr(meta, attr, None)
            if value is not None:
                parts.append(f"{label} {value}")
    return ", ".join(parts)


def _default_text(info: FieldInfo) -> str:
    if info.is_required():
        return "required"
    if info.default_factory is not None:
        value: Any = cast(Callable[[], Any], info.default_factory)()
    else:
        value = info.default
    if isinstance(value, BaseModel):
        return "nested defaults"
    if isinstance(value, list) and value and isinstance(value[0], BaseModel):
        return f"{len(value)} built-in entries"
    return _json_text(value)


def _merge_text(model: type[BaseModel], name: str) -> str:
    meta = field_meta(model, name)
    parts: list[str] = [meta.merge]
    if meta.tighten is not None:
        parts.append(f"tighten {meta.tighten}")
    if meta.order:
        parts.append("order " + ", ".join(meta.order))
    if meta.mergeable_set:
        parts.append("mergeable set (union)")
    if meta.ceiling is not None:
        parts.append(f"capped by {meta.ceiling}")
    if meta.secret_ref:
        parts.append("secret name")
    if meta.floor:
        parts.append("floor rules")
    if meta.tool_names:
        parts.append("tool names")
    return ", ".join(parts)


def _nested(annotation: Any) -> tuple[str, type[BaseModel]] | None:
    inner, _ = _split_optional(annotation)
    inner = _unwrap_annotated(inner)
    if isinstance(inner, type) and issubclass(inner, BaseModel):
        return "", inner
    origin = get_origin(inner)
    args = get_args(inner)
    if origin is dict and len(args) == 2:
        value, _ = _split_optional(args[1])
        if isinstance(value, type) and issubclass(value, BaseModel):
            return ".{key}", value
    if origin is list and args:
        item, _ = _split_optional(args[0])
        if isinstance(item, type) and issubclass(item, BaseModel):
            return "[]", item
    return None


def _walk(
    path: str, model: type[BaseModel], expand_squad: bool, out: list[_Node]
) -> None:
    out.append(_Node(path, model))
    for name, info in model.model_fields.items():
        nested = _nested(info.annotation)
        if nested is None:
            continue
        suffix, sub = nested
        if sub is SquadFields and not expand_squad:
            continue
        _walk(
            f"{path}.{name}{suffix}" if path else f"{name}{suffix}",
            sub,
            expand_squad,
            out,
        )


def _section_table(model: type[BaseModel], path: str) -> list[str]:
    lines = [
        "| Key | Type | Default | Merge policy | Constraints | Description |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, info in model.model_fields.items():
        nested = _nested(info.annotation)
        if nested is not None:
            suffix, sub = nested
            target = f"{path}.{name}{suffix}" if path else f"{name}{suffix}"
            if sub is SquadFields:
                where = f"see {_code(_CONFIG_ANCHOR)}"
            else:
                where = f"see {_code(target)}"
            kind = {
                "": "section",
                "[]": "list of sections",
                ".{key}": "map of sections",
            }
            cells = [
                _code(name),
                _cell(f"{kind[suffix]}, {where}"),
                "nested defaults",
                _cell(_merge_text(model, name)),
                "",
                _cell(info.description or ""),
            ]
        else:
            cells = [
                _code(name),
                _cell(_type_text(info.annotation)),
                _cell(_default_text(info)),
                _cell(_merge_text(model, name)),
                _cell(_constraints(info)),
                _cell(info.description or ""),
            ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _render_model_tree(
    root: type[BaseModel], root_name: str, expand_squad: bool
) -> list[str]:
    nodes: list[_Node] = []
    _walk(root_name, root, expand_squad, nodes)
    out: list[str] = []
    for node in nodes:
        if node.path:
            deep = "." in node.path or "[" in node.path
            out.append(f"{'###' if deep else '##'} {_code(node.path)}")
            out.append("")
        out.extend(_section_table(node.model, node.path))
        out.append("")
    return out


def render_configuration() -> str:
    lines = [
        MARKER,
        "",
        "# Configuration reference",
        "",
        "Generated from `code_squad/_common/config/schema.py`. Every key is optional",
        "unless the table says `required`, and every table shows the built-in default.",
        "Merge policies: `free` (any layer may set it), `tighten_only` (a repository "
        "or",
        "call may only move it toward stricter), `org_only` (only the organisation "
        "file",
        "or the project registry may set it). Concepts are explained in",
        "[Configuration concepts](../configuration/concepts.md).",
        "",
        "## File kinds",
        "",
        "| File | Model | Notes |",
        "| --- | --- | --- |",
        "| Organisation file (`squad.yaml`) | `SquadConfig` | Full schema, org_only "
        "keys allowed. |",
        "| Project registry (`projects.yaml`) | `ProjectsFile` and `ProjectEntry` | "
        "Matches, provider and secret names, `extends`, `overrides`. |",
        "| Repository file (`.squad/config.yml`) | `RepoConfig` | Same keys as the "
        "organisation file plus `extends`. org_only keys are rejected. |",
        "| Accepted findings (`.squad/baseline.yml`) | `Baseline` | Each entry needs "
        "an expiry date. Not applied at run time yet. |",
        "",
    ]
    lines.append(f"## {_CONFIG_ANCHOR}")
    lines.append("")
    lines.extend(_render_model_tree(SquadFields, "", expand_squad=True))
    lines.extend(
        [
            "## Repository file extra key",
            "",
            "| Key | Type | Default | Merge policy | Constraints | Description |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    extends = RepoConfig.model_fields["extends"]
    extends_cells = [
        _code("extends"),
        _cell(_type_text(extends.annotation)),
        _cell(_default_text(extends)),
        "free",
        _cell(_constraints(extends)),
        _cell(extends.description or ""),
    ]
    lines.append("| " + " | ".join(extends_cells) + " |")
    lines.append("")
    lines.append("## Project registry entries")
    lines.append("")
    lines.extend(_render_model_tree(ProjectsFile, "projects.yaml", expand_squad=False))
    lines.append("## Accepted findings file")
    lines.append("")
    lines.extend(_render_model_tree(Baseline, "baseline.yml", expand_squad=False))
    return "\n".join(lines).rstrip() + "\n"


def render_environment() -> str:
    lines = [
        MARKER,
        "",
        "# Environment variables",
        "",
        "Generated from `code_squad/_common/config/bootstrap.py`. Each variable is "
        "read by",
        "the process at start-up or per request, as described in the deployment pages.",
        "",
        render_env_table(),
        "## Nested configuration",
        "",
        NESTING_NOTE,
        "",
        "## Other variables read by the code",
        "",
        "These are read by the code but are not yet in the bootstrap table.",
        "",
        "| Variable | Description | Default |",
        "| --- | --- | --- |",
    ]
    for name, description, default in _UNLISTED_VARIABLES:
        lines.append(f"| {_code(name)} | {_cell(description)} | {_cell(default)} |")
    lines.append("")
    return "\n".join(lines)


def _usage_by_tool(specs: Iterable[AgentSpec]) -> dict[str, list[str]]:
    usage: dict[str, list[str]] = defaultdict(list)
    for spec in specs:
        for tool in spec.tools:
            usage[tool_name(tool)].append(spec.name)
    return usage


def render_tool_policy() -> str:
    usage = _usage_by_tool(all_specs())
    lines = [
        MARKER,
        "",
        "# Tool policy",
        "",
        "Generated from `code_squad/_common/tool_policy.py` and the `tools` of every "
        "built-in",
        "agent specification. Extra agents declared in configuration use the presets",
        "`review_readonly` and `review_publish` and are not listed here.",
        "",
        "Classes: `read` tools change nothing; `local_mutation` tools change only the",
        "sandbox working copy; `external_write` tools change a remote system and are "
        "refused",
        "when posting is disabled (dry-run).",
        "",
        "| Tool | Class | Agents |",
        "| --- | --- | --- |",
    ]
    for name in sorted(usage):
        klass = classify(name)
        agents = ", ".join(_code(agent) for agent in sorted(set(usage[name])))
        lines.append(f"| {_code(name)} | {klass.value} | {agents} |")
    unused = sorted(set(TOOL_POLICY) - set(usage))
    lines.extend(["", "## Classified but not exposed by a built-in agent", ""])
    if unused:
        lines.extend(f"- {_code(name)} ({TOOL_POLICY[name].value})" for name in unused)
    else:
        lines.append("None.")
    writes = sorted(
        name for name, klass in TOOL_POLICY.items() if klass is ToolClass.EXTERNAL_WRITE
    )
    lines.extend(["", "## External write tools", ""])
    lines.append(", ".join(_code(name) for name in writes) + ".")
    lines.append("")
    return "\n".join(lines)


def _mark(value: bool) -> str:
    return "yes" if value else "no"


def render_vcs_capabilities() -> str:
    gitlab = GitLabProvider.capabilities
    app = GitHubProvider(auth=AppAuth("1", "fake-private-key-for-tests")).capabilities
    pat = GitHubProvider(auth=TokenAuth("fake-token-for-tests")).capabilities
    lines = [
        MARKER,
        "",
        "# VCS capability matrix",
        "",
        "Generated from the capability sets of `GitLabProvider` and `GitHubProvider`",
        "(`code_squad/_common/vcs/base.py`). GitHub authenticates either as a GitHub "
        "App",
        "or with a personal access token, which changes the capability set.",
        "",
        "| Capability | GitLab | GitHub (App) | GitHub (token) |",
        "| --- | --- | --- | --- |",
    ]
    for capability in Capability:
        lines.append(
            f"| {_code(capability.value)} | {_mark(capability in gitlab)} | "
            f"{_mark(capability in app)} | {_mark(capability in pat)} |"
        )
    lines.extend(
        ["", "## Fallbacks", "", "| Capability | Fallback or effect |", "| --- | --- |"]
    )
    for capability in Capability:
        fallback = _cell(_CAPABILITY_FALLBACKS[capability])
        lines.append(f"| {_code(capability.value)} | {fallback} |")
    lines.append("")
    return "\n".join(lines)


def render_agents() -> str:
    specs = all_specs()
    lines = [
        MARKER,
        "",
        "# Agent defaults",
        "",
        "Generated from the `SPEC` of every built-in agent. These are the built-in "
        "defaults.",
        "The organisation file, the project registry and the repository file can "
        "change the",
        "model, token and iteration settings (`agents.<id>`), within the platform "
        "limits.",
        "",
        "| Id | Role | Modes | Default model | Max tokens | Temperature | Max "
        "iterations | Tools | External writes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for spec in specs:
        names = [tool_name(tool) for tool in spec.tools]
        writes = [name for name in names if classify(name) is ToolClass.EXTERNAL_WRITE]
        cells = [
            _code(spec.name),
            _cell(spec.role),
            _cell(", ".join(spec.modes)),
            _code(spec.model_id),
            str(spec.max_tokens),
            f"{spec.temperature:g}",
            str(spec.max_iterations),
            str(len(names)),
            _cell(", ".join(_code(name) for name in writes) or "none"),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "## Descriptions", ""])
    lines.extend(f"- {_code(spec.name)}: {_cell(spec.description)}" for spec in specs)
    lines.append("")
    return "\n".join(lines)


def render_all() -> dict[Path, str]:
    _clean_environment()
    return {
        REFERENCE_DIR / "configuration.md": render_configuration(),
        REFERENCE_DIR / "environment.md": render_environment(),
        REFERENCE_DIR / "tool-policy.md": render_tool_policy(),
        REFERENCE_DIR / "vcs-capabilities.md": render_vcs_capabilities(),
        REFERENCE_DIR / "agents.md": render_agents(),
    }


def main(argv: list[str]) -> int:
    check = "--check" in argv
    drift: list[str] = []
    for path, text in render_all().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        if check:
            drift.append(str(path.relative_to(ROOT)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    for name in drift:
        print(f"docs drift: {name} (run: just docs-gen)", file=sys.stderr)
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
