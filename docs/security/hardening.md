# Hardening

This page is the checklist for a production deployment, followed by the known defects that affect security. Work through
the checklist before the first real review. The threat model explains why each item matters:
[Threat model](threat-model.md). The tool classes are in the [tool policy reference](../reference/tool-policy.md).

## Checklist

### Network

- [ ] `networkPolicy.enabled` is true, and the CNI enforces NetworkPolicy. Check with a test pod that a disallowed
      destination times out.
- [ ] Every CIDR is a real range, not a documentation placeholder. The examples use RFC 5737 addresses on purpose.
- [ ] `/invocations` is not reachable from outside the cluster. The chart's Ingress does not route it. If an external route
      is needed, it sits behind an authenticating proxy or mTLS.
- [ ] Callers inside the cluster send the shared bearer token (see [API authentication](#api-authentication)), and no pod
      logs the start-up warning that the token is not set.
- [ ] The webhook ingress exposes only `/webhooks/gitlab` and `/webhooks/github`, and TLS is enforced.
- [ ] Egress proxy, when used, is the only path for the VCS and advisory clients (`EGRESS_PROXY_URL`). Model traffic follows
      `HTTPS_PROXY` settings; see [Network and egress](../deployment/network-and-egress.md).

### Secrets and identity

- [ ] Secret values are not in any values file, ConfigMap, environment variable list or Git history. Scan with `just secret-scan`
      before committing.
- [ ] `secrets.allowed_patterns` is set in the organisation file to the naming rule the team uses.
- [ ] Each VCS token has the minimum scopes in [GitLab token scopes](../vcs/gitlab.md) or the App permissions in
      [GitHub](../vcs/github.md). `write_repository` and Contents write are granted only when `pam` runs.
- [ ] Webhook secrets are long random values, and `webhooks.secretName` moves them to a Secret that only michael mounts.
- [ ] `SQUAD_API_TOKEN` is a long random value (for example 32 bytes from a CSPRNG), stored in a Secret, and rotated with a
      rolling restart of every agent.
- [ ] Credentials are rotated on a schedule, and a rotation has been rehearsed.

### Posting and policy

- [ ] `posting.force_dry_run` is set to `true` in the organisation file until the team has reviewed a trial. Turn it off
      deliberately, once, for the environment.
- [ ] `vcs.approve_mode` is `none` unless the team has decided otherwise in writing.
- [ ] `trigger.allowed_commenters` lists the people who may start a run from a comment.
- [ ] `routing.specialists_post` is false.
- [ ] `vcs.bot_username` is set for every project that receives webhooks.
- [ ] `repo_config.allow_head_ref` and `skills_ref: head` are off.

### Sandbox and cluster

- [ ] `sandbox.enabled` is true, and `SANDBOX_NAMESPACE` is set. Without it, pam uses the local process sandbox inside its
      own container. See the warning in [pam](../agents/pam.md).
- [ ] The sandbox namespace exists with the `restricted` Pod Security label, and `kubectl auth can-i` confirms the grants in
      [RBAC](../deployment/rbac.md).
- [ ] `devops.allowedNamespaces` is the smallest list that darryl needs, and `devops.clusterWide` is false.
- [ ] `ops.allowed_namespaces` in the organisation file matches the chart's list.
- [ ] Pods run with the chart's security context (non-root, read-only root filesystem, no capabilities, RuntimeDefault seccomp).
- [ ] Image tags are immutable (a commit or a version), not `latest`. Use `scripts/bump_image.py` to set them.
- [ ] Images are scanned by your registry before deployment. The squad does not scan its own image.

### Configuration

- [ ] `limits.*` reflects the budgets you accept. These are platform ceilings for every project.
- [ ] `security.sources` is set to the sources you can reach, and `security.offline_mode` is chosen deliberately.
- [ ] `ops.redaction_patterns` includes the internal token formats of your organisation.
- [ ] Organisation and registry files pass `uv run squad config validate` before they are deployed.

### Operations

- [ ] Metrics are scraped, and the alerts in `deploy/observability/prometheus-rules.yaml` are loaded. Note the known gap in
      [Runbook](../operations/runbook.md#known-gaps-in-the-alerts).
- [ ] Log retention and access meet your policy. Logs carry metadata only, but invocation ids link them to change requests.
- [ ] A dry-run review is run after every configuration change.

## API authentication

`POST /invocations` and `GET /jobs/{id}` accept an optional shared bearer token.

- Configure it with `SQUAD_API_TOKEN`, or with `SQUAD_API_TOKEN_FILE` naming a file that holds the token. The Helm chart
  sets `SQUAD_API_TOKEN` from `api.tokenSecret` on every agent.
- When configured, a request without `Authorization: Bearer <token>` gets `401` with `WWW-Authenticate: Bearer`. The
  token is compared in constant time (`hmac.compare_digest`). The scheme name is case-insensitive.
- Not gated, whatever the setting: `/ping`, `/ready`, `/metrics`, and `/webhooks/gitlab` and `/webhooks/github`, which
  keep their own signature checks.
- michael sends the same header to every specialist, so the token must be the same on every agent.
- When unset, the endpoints are open, and each process logs one warning at start-up.
- The token is read once at start-up. Rotate it by updating the Secret and restarting the pods. A file that is set but
  empty stops the process at start-up.

Limits: there is one shared token and no per-caller identity, so a leaked token gives full access to the two endpoints.
The token does not protect the webhook routes and does not replace keeping `/invocations` off the public ingress. The
brief's non-goals allow a shared bearer token or mTLS at the ingress, and this is the first of the two.

## Known defects that affect security

These are defects and gaps in the version documented here. The owners should fix them before production use. They are also
listed in the [handoff](../HANDOFF.md#known-limitations).

| # | Defect | Effect | Workaround |
| --- | --- | --- | --- |
| D2 | With `SANDBOX_NAMESPACE` unset, pam uses the local process sandbox. The chart's `minimal-kind.yaml` turns the sandbox off. | Repository commands run in the pam container without isolation. | Keep `sandbox.enabled: true` outside disposable clusters. |
| D3 | `/invocations` and `/jobs/{id}` are open unless `SQUAD_API_TOKEN` is set. | Without the token, any caller that reaches the Service can start reviews, and can publish with `post: true` unless the organisation forces dry run. | Set `api.tokenSecret` (see [API authentication](#api-authentication)); keep the network controls; `posting.force_dry_run` in the organisation file. |
| D6 | The Secret is mounted whole into every agent pod. | A compromised agent can read every secret key. | Split Secrets by agent (planned); keep the number of keys small. |
| D7 | The TTL of sandbox pods is stored but not applied. | A crashed run can leave a pod until its deadline. | Keep `activeDeadlineSeconds` short; check for orphaned pods. |
| D8 | `security.accepted_risks` can be added by a repository layer. | A repository can accept an advisory for its own change. | Restrict the field to the organisation layer (open point, ADR 0009). |
| D9 | `llm.api_key_secret` in the organisation file does not select the gateway key; the key comes from `LLM_API_KEY` or `LLM_API_KEY_FILE`. | Operators may believe a control is configured when it is not. | Use the keys in [Configuration reference](../reference/configuration.md). |

## Reporting a vulnerability

Report a suspected vulnerability privately to the platform team that owns this repository, not in a public issue or change
request. Include the version or commit, the configuration that matters (with secrets removed), the steps to reproduce, and
the expected and actual behaviour. Do not include real tokens or customer data in the report. The team acknowledges a report,
assesses it against the threat model, and records the decision in an ADR when the fix changes a control.
