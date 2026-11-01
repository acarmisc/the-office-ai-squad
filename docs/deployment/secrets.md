# Secrets

The squad never stores secret values in configuration. Configuration holds secret **names**, and a secret
provider resolves each name to a value when it is needed. The rules below are enforced in code
(`_common/secrets/`, `_common/config/schema.py`), so a mistake in a values file cannot put a token into a
ConfigMap without a validation error.

## Names and rules

- A secret name matches `^[a-z0-9][a-z0-9._-]{0,252}$`.
- It must also fully match one of `secrets.allowed_patterns`, which is organisation-only. The default is
  `^[a-z0-9][a-z0-9._-]*$`.
- A name containing a path separator or `..` is refused before any file is opened.
- A value that looks like a token (for example a prefix such as `glpat-`, `ghp_`, `sk-`) is refused in the
  per-call `project_config` fields, so a caller cannot pass a raw secret where a name is expected.

## Secret names the platform reads

| Name | Read by | Used for | Required |
| --- | --- | --- | --- |
| `llm-api-key` | Chart (`llm.apiKeySecret`), exposed as `LLM_API_KEY` | Gateway key for every model call | Yes |
| Name in `api.tokenSecret.name`, key `api.tokenSecret.key` | Chart, exposed as `SQUAD_API_TOKEN` on every agent | Shared bearer token for `/invocations` and `/jobs/{id}` | No: without it the endpoints are open |
| `vcs-token` | Bootstrap fallback (`VCS_TOKEN` or `VCS_TOKEN_FILE`) | Single-project VCS token, when no registry entry names a token | Only for the single-project fallback |
| Any name in `vcs.auth.token_secret` | Registry or organisation file | Token for a project (GitLab token, or a GitHub token) | For each project using a token |
| Any name in `vcs.auth.private_key_secret` | Registry or organisation file | GitHub App private key, PEM text | For each project using a GitHub App |
| `gitlab-webhook-secret` | michael's webhook gateway | Verifies `X-Gitlab-Token` | When the GitLab webhook is enabled |
| `github-webhook-secret` | michael's webhook gateway | Verifies `X-Hub-Signature-256` | When the GitHub webhook is enabled |
| `nvd-api-key` | dwight | Higher NVD rate limit | No |
| `ghsa-token` | dwight | GitHub advisory queries | No |
| `jira-api-token` | pam (task text) | Jira read access, with `JIRA_BASE_URL` | Only with Jira |

The GitHub App **id** is not a secret. It is `vcs.auth.app_id` in configuration, so the sample Secrets in
`deploy/secrets-examples/` do not carry it.

## Providers

| Provider | Selected by | Behaviour | Use it for |
| --- | --- | --- | --- |
| `k8s_files` (default) | `secrets.provider: k8s_files` | Reads a file named exactly as the secret, from `SECRETS_DIR` (default `/var/run/secrets/squad`). Trailing carriage returns and line feeds are removed. | Production in Kubernetes. |
| `env` | `secrets.provider: env` | Reads `SQUAD_SECRET_<NAME>`, with dashes, dots and slashes turned into underscores and the name upper-cased. | Development and tests only. |
| `file` | Schema accepts it | Not implemented. The factory refuses it. | Do not use. |
| `vault` | Schema accepts it | A stub. It needs an optional package that is not a dependency and does not read values. | Do not use. |

Bootstrap variables take precedence over the provider. `LLM_API_KEY` or `LLM_API_KEY_FILE`, and
`VCS_TOKEN` or `VCS_TOKEN_FILE`, are read first. `LLM_API_KEY` is read from the environment by the model
factory, so the chart's `secretKeyRef` is what delivers the gateway key.

## Create the Secret

Keep real values out of Git. The examples in `deploy/secrets-examples/` are placeholders, and the sealed-secret
sample contains fake ciphertext that only shows the structure.

Plain Secret, created with your own tooling:

```bash
kubectl -n code-squad create secret generic code-squad-secrets \
  --from-literal=llm-api-key="$LLM_KEY" \
  --from-literal=gitlab-webhook-secret="$GITLAB_WEBHOOK" \
  --from-file=github-app-key=./app-key.pem
```

Each key becomes a file under `/var/run/secrets/squad` in every agent pod. The file names are the secret names.
Use `secrets.existingSecret` in the chart to point at this Secret.

For GitOps, use Sealed Secrets (`deploy/secrets-examples/sealed-secret.yaml` shows the shape) or External Secrets
(`deploy/secrets-examples/external-secret.yaml` syncs the keys from a secret store). The chart's
`values-examples/external-secrets.yaml` shows the reference. Both produce a Secret with the same key names.

## Rotation

1. Create the new credential at the VCS host or the gateway, with the same scopes.
2. Update the value in the secret store, or the Secret, under the same key name.
3. The squad reads secret files at use time, so no restart is needed for a file-backed Secret. Confirm with a
   dry-run invocation for a project that uses the secret.
4. Revoke the old credential.

A GitHub App private key can be added as a second key and the registry switched to it, which keeps the old key
usable until the switch is verified.

## What each pod can read

Every agent pod mounts the whole Secret. A pod can therefore read every key in the Secret, including the webhook
secrets and the VCS tokens, even if its agent does not use them. This is a residual risk. The chart's
`webhooks.secretName` moves the webhook secrets to a separate Secret that only michael mounts. Splitting the other
keys by agent is a planned hardening step (see [Hardening](../security/hardening.md)).

## Logging and output

Secret values are never written to logs, traces, metrics or results. Tool output from repositories and clusters is
redacted before the model sees it, and a token that a tool echoes is masked. These are defences in depth; keep the
values out of places where they are not needed.
