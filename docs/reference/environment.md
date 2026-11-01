<!-- generated — do not edit. Source: scripts/gen_docs.py. Regenerate with: just docs-gen -->

# Environment variables

Generated from `code_squad/_common/config/bootstrap.py`. Each variable is read by
the process at start-up or per request, as described in the deployment pages.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `AGENT_NAME` | yes | - | Agent id this process serves (michael, jim, ...). |
| `LLM_BASE_URL` | yes | - | LiteLLM gateway URL. |
| `LLM_API_KEY` | no | - | Gateway key. Prefer LLM_API_KEY_FILE. |
| `LLM_API_KEY_FILE` | no | - | Path to a file holding the gateway key. |
| `VCS_PROVIDER` | no | - | Single-project fallback: gitlab, github or auto. |
| `VCS_BASE_URL` | no | - | Single-project fallback: VCS API base URL. |
| `VCS_TOKEN` | no | - | Single-project fallback: VCS token. Prefer the file. |
| `VCS_TOKEN_FILE` | no | - | Single-project fallback: file holding the VCS token. |
| `SECRETS_DIR` | no | `/var/run/secrets/squad` | Directory of secret files (k8s_files provider). |
| `SQUAD_CONFIG_FILE` | no | `/etc/squad/squad.yaml` | Org configuration file. |
| `SQUAD_PROJECTS_DIR` | no | `/etc/squad/projects` | Project registry: a file or a directory. |
| `SQUAD_PROFILES_DIR` | no | `/etc/squad/profiles` | Extra profile files, overriding built-ins. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | - | OTLP collector endpoint for traces. |
| `SESSION_STORE_URL` | no | - | Redis URL for async jobs (memory store if unset). |
| `ORCHESTRATOR_SPECIALIST_URLS` | no | - | Specialist base URLs for michael, as key=url pairs. |
| `EGRESS_PROXY_URL` | no | - | Outbound HTTPS proxy for advisory and VCS calls. |
| `AGENT_MODEL_ID` | no | - | Override the agent's model alias. |
| `AGENT_MAX_TOKENS` | no | - | Override the agent's output token cap. |
| `AGENT_MAX_ITERATIONS` | no | - | Override the agent's turn limit. |
| `AGENT_TEMPERATURE` | no | - | Override the agent's temperature (0 to 2). |
| `AGENT_PROMPT_FILE` | no | - | Override the agent's prompt file. |
| `SQUAD_API_TOKEN` | no | - | Shared bearer token for POST /invocations and GET /jobs/{id}. Unset means no token check. Prefer the file. |
| `SQUAD_API_TOKEN_FILE` | no | - | File holding the shared bearer token. Read once at start-up. |
| `LOG_LEVEL` | no | `INFO` | Log level of the process. |
| `WEBHOOK_PROVIDERS` | no | - | Comma-separated providers whose webhook route michael registers: gitlab, github. Unset means no /webhooks route exists. |
| `WEBHOOK_SECRETS_DIR` | no | - | Directory holding gitlab-webhook-secret and github-webhook-secret. Unset means the secret provider is used. |
| `POD_NAMESPACE` | no | `default` | Namespace used for specialist service DNS names when no URL is configured. |
| `SANDBOX_NAMESPACE` | no | - | Selects the Kubernetes sandbox for pam when set. When unset, pam uses the local process sandbox, which is for development only. |
| `SANDBOX_IMAGE` | no | - | Sandbox pod image. Required when SANDBOX_NAMESPACE is set. |
| `SANDBOX_ACTIVE_DEADLINE_SECONDS` | no | `1800` | Hard wall-clock limit of a sandbox pod. |
| `SANDBOX_TTL_SECONDS_AFTER_FINISHED` | no | `300` | Stored on the sandbox backend but not applied: pods carry no TTL field. |
| `SANDBOX_RESOURCES_JSON` | no | `{"requests": {"cpu": "250m", "memory": "512Mi"}, "limits": {"cpu": "2", "memory": "2Gi"}}` | JSON object with requests and limits for each sandbox pod. |
| `MICHAEL_LLM_INTENT` | no | `off` | Opt-in: a small model classifies requests that the rules cannot classify. |
| `MICHAEL_LLM_SUMMARY` | no | `off` | Opt-in: a model writes a neutral narrative above the deterministic summary. |
| `MICHAEL_SUMMARY_MODEL` | no | `sonnet-5-5` | Model alias for the optional summary narrative. |
| `JIRA_BASE_URL` | no | - | Jira base URL. When set and the jira-api-token secret is available, pam reads task text from Jira (read only) instead of the VCS issue tracker. |
| `SQUAD_SECRET_<NAME>` | no | - | Secret values for the env secret provider (development and tests only). |
| `KUBERNETES_SERVICE_HOST` | no | - | Set by Kubernetes. darryl uses it to detect in-cluster configuration. |

## Nested configuration

Any configuration key can be set with SQUAD__SECTION__KEY (lowercase path, double underscores between segments), for example SQUAD__AGENTS__DWIGHT__MODEL. Values are read as YAML scalars or JSON. Quote strings that YAML would misread, and note that keys inside maps are lowercased (use the YAML file for rule ids).
