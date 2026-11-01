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
    # False for patterns and platform-set names, which .env.example leaves out.
    in_example: bool = True


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
    EnvVar(
        "SQUAD_API_TOKEN",
        "Shared bearer token for POST /invocations and GET /jobs/{id}. Required unless "
        "SQUAD_ALLOW_UNAUTHENTICATED=1; without either, both endpoints refuse every "
        "request. Prefer the file.",
        None,
        False,
    ),
    EnvVar(
        "SQUAD_API_TOKEN_FILE",
        "File holding the shared bearer token. Read once at start-up.",
        None,
        False,
    ),
    EnvVar(
        "SQUAD_ALLOW_UNAUTHENTICATED",
        "Set to 1 to keep /invocations and /jobs open when no API token is configured. "
        "Local demos and tests only; the chart sets it only when "
        "api.allowUnauthenticated is true.",
        None,
        False,
    ),
    EnvVar(
        "SQUAD_MAX_REQUEST_BYTES",
        "Largest accepted /invocations request body. Larger bodies get 413 before "
        "parsing.",
        "1000000",
        False,
    ),
    EnvVar(
        "SQUAD_MAX_WEBHOOK_BYTES",
        "Largest accepted webhook body. Applied before signature verification.",
        "1048576",
        False,
    ),
    EnvVar(
        "SQUAD_DOCS_URL",
        "Documentation link appended to the /squad help reply on the VCS.",
        None,
        False,
    ),
    EnvVar(
        "ALLOW_LOCAL_SANDBOX",
        "Set to 1 to let pam run without the Kubernetes sandbox (SANDBOX_NAMESPACE "
        "unset). Development only; pam refuses to start otherwise.",
        None,
        False,
    ),
    EnvVar("LOG_LEVEL", "Log level of the process.", "INFO", False),
    EnvVar(
        "WEBHOOK_PROVIDERS",
        "Comma-separated providers whose webhook route michael registers: gitlab, "
        "github. Unset means no /webhooks route exists.",
        None,
        False,
    ),
    EnvVar(
        "WEBHOOK_SECRETS_DIR",
        "Directory holding gitlab-webhook-secret and github-webhook-secret. Unset "
        "means the secret provider is used.",
        None,
        False,
    ),
    EnvVar(
        "POD_NAMESPACE",
        "Namespace used for specialist service DNS names when no URL is configured.",
        "default",
        False,
    ),
    EnvVar(
        "SANDBOX_NAMESPACE",
        "Selects the Kubernetes sandbox for pam when set. When unset, pam uses the "
        "local process sandbox, which is for development only.",
        None,
        False,
    ),
    EnvVar(
        "SANDBOX_IMAGE",
        "Sandbox pod image. Required when SANDBOX_NAMESPACE is set.",
        None,
        False,
    ),
    EnvVar(
        "SANDBOX_ACTIVE_DEADLINE_SECONDS",
        "Hard wall-clock limit of a sandbox pod.",
        "1800",
        False,
    ),
    EnvVar(
        "SANDBOX_TTL_SECONDS_AFTER_FINISHED",
        "Stored on the sandbox backend but not applied: pods carry no TTL field.",
        "300",
        False,
    ),
    EnvVar(
        "SANDBOX_RESOURCES_JSON",
        "JSON object with requests and limits for each sandbox pod.",
        '{"requests": {"cpu": "250m", "memory": "512Mi"}, "limits": {"cpu": "2", '
        '"memory": "2Gi"}}',
        False,
    ),
    EnvVar(
        "MICHAEL_LLM_INTENT",
        "Opt-in: a small model classifies requests that the rules cannot classify.",
        "off",
        False,
    ),
    EnvVar(
        "MICHAEL_LLM_SUMMARY",
        "Opt-in: a model writes a neutral narrative above the deterministic summary.",
        "off",
        False,
    ),
    EnvVar(
        "MICHAEL_SUMMARY_MODEL",
        "Model alias for the optional summary narrative.",
        "sonnet-5-5",
        False,
    ),
    EnvVar(
        "JIRA_BASE_URL",
        "Jira base URL. When set and the jira-api-token secret is available, pam reads "
        "task text from Jira (read only) instead of the VCS issue tracker.",
        None,
        False,
    ),
    EnvVar(
        "SQUAD_SECRET_<NAME>",
        "Secret values for the env secret provider (development and tests only).",
        None,
        False,
        in_example=False,
    ),
    EnvVar(
        "KUBERNETES_SERVICE_HOST",
        "Set by Kubernetes. darryl uses it to detect in-cluster configuration.",
        None,
        False,
        in_example=False,
    ),
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
        if not var.in_example:
            continue
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
