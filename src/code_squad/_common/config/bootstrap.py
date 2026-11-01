"""Bootstrap environment variables, documented from one table (brief 4.6).

The table renders the reference section and ``.env.example``. Nested config is set
with ``SQUAD__SECTION__KEY`` variables (see ``loader.apply_env_overrides``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

from code_squad._common.config.schema import ProjectEntry
from code_squad._common.secrets.base import VCS_TOKEN_SECRET


class EnvVar(NamedTuple):
    name: str
    description: str
    default: str | None
    required: bool


NESTING_NOTE: str = (
    "Any configuration key can be set with SQUAD__SECTION__KEY (lowercase path, "
    "double underscores between segments), for example SQUAD__AGENTS__DWIGHT__MODEL. "
    "Values are read as YAML scalars or JSON. Quote strings that YAML would misread, "
    "and note that keys inside maps are lowercased (use the YAML file for rule ids)."
)

BOOTSTRAP_ENV: tuple[EnvVar, ...] = (
    EnvVar(
        "AGENT_NAME", "Agent id this process serves (michael, jim, ...).", None, True
    ),
    EnvVar("LLM_BASE_URL", "LiteLLM gateway URL.", None, True),
    EnvVar("LLM_API_KEY", "Gateway key. Prefer LLM_API_KEY_FILE.", None, False),
    EnvVar("LLM_API_KEY_FILE", "Path to a file holding the gateway key.", None, False),
    EnvVar(
        "VCS_PROVIDER", "Single-project fallback: gitlab, github or auto.", None, False
    ),
    EnvVar("VCS_BASE_URL", "Single-project fallback: VCS API base URL.", None, False),
    EnvVar(
        "VCS_TOKEN", "Single-project fallback: VCS token. Prefer the file.", None, False
    ),
    EnvVar(
        "VCS_TOKEN_FILE",
        "Single-project fallback: file holding the VCS token.",
        None,
        False,
    ),
    EnvVar(
        "SECRETS_DIR",
        "Directory of secret files (k8s_files provider).",
        "/var/run/secrets/squad",
        False,
    ),
    EnvVar(
        "SQUAD_CONFIG_FILE", "Org configuration file.", "/etc/squad/squad.yaml", False
    ),
    EnvVar(
        "SQUAD_PROJECTS_DIR",
        "Project registry: a file or a directory.",
        "/etc/squad/projects",
        False,
    ),
    EnvVar(
        "SQUAD_PROFILES_DIR",
        "Extra profile files, overriding built-ins.",
        "/etc/squad/profiles",
        False,
    ),
    EnvVar(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTLP collector endpoint for traces.",
        None,
        False,
    ),
    EnvVar(
        "SESSION_STORE_URL",
        "Redis URL for async jobs (memory store if unset).",
        None,
        False,
    ),
    EnvVar(
        "ORCHESTRATOR_SPECIALIST_URLS",
        "Specialist base URLs for michael, as key=url pairs.",
        None,
        False,
    ),
    EnvVar(
        "EGRESS_PROXY_URL",
        "Outbound HTTPS proxy for advisory and VCS calls.",
        None,
        False,
    ),
    EnvVar("AGENT_MODEL_ID", "Override the agent's model alias.", None, False),
    EnvVar("AGENT_MAX_TOKENS", "Override the agent's output token cap.", None, False),
    EnvVar("AGENT_MAX_ITERATIONS", "Override the agent's turn limit.", None, False),
    EnvVar(
        "AGENT_TEMPERATURE", "Override the agent's temperature (0 to 2).", None, False
    ),
    EnvVar("AGENT_PROMPT_FILE", "Override the agent's prompt file.", None, False),
)


def render_env_table() -> str:
    rows = [
        "| Variable | Required | Default | Description |",
        "| --- | --- | --- | --- |",
    ]
    for var in BOOTSTRAP_ENV:
        default = f"`{var.default}`" if var.default is not None else "-"
        required = "yes" if var.required else "no"
        rows.append(f"| `{var.name}` | {required} | {default} | {var.description} |")
    return "\n".join(rows) + "\n"


def render_env_example() -> str:
    lines: list[str] = []
    for var in BOOTSTRAP_ENV:
        lines.append(f"# {var.description}")
        lines.append(f"{var.name}={var.default or ''}")
        lines.append("")
    return "\n".join(lines)


def single_project_entry(env: Mapping[str, str], project: str) -> ProjectEntry | None:
    """Synthesise a registry entry from VCS_PROVIDER and VCS_BASE_URL when present."""
    provider = env.get("VCS_PROVIDER", "").strip()
    base_url = env.get("VCS_BASE_URL", "").strip()
    if not provider or not base_url:
        return None
    return ProjectEntry.model_validate(
        {
            "match": project,
            "provider": provider,
            "base_url": base_url,
            "auth": {"token_secret": VCS_TOKEN_SECRET},
        }
    )
