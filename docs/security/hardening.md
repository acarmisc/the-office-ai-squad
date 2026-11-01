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
- [ ] `api.tokenSecret` is set (or `api.allowUnauthenticated` is false), and `SQUAD_API_TOKEN` is a long random value (for example 32 bytes from a CSPRNG), stored in a Secret, and rotated with a
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

`POST /invocations` and `GET /jobs/{id}` require a shared bearer token. Authentication fails closed.

- Configure it with `SQUAD_API_TOKEN`, or with `SQUAD_API_TOKEN_FILE` naming a file that holds the token. The Helm chart
  sets `SQUAD_API_TOKEN` from `api.tokenSecret` on every agent, and `api.tokenSecret` is required unless
  `api.allowUnauthenticated` is true.
- With no token and no explicit opt-in, both endpoints answer `401` to every request, and each process logs a warning at
  start-up. The opt-in is `SQUAD_ALLOW_UNAUTHENTICATED=1`, which is set only by the local demos (Compose and the kind
  example) and by `api.allowUnauthenticated: true`. Any other value keeps the endpoints closed.
- When a token is configured, a request without `Authorization: Bearer <token>` gets `401` with `WWW-Authenticate: Bearer`.
  The token is compared in constant time (`hmac.compare_digest`). The scheme name is case-insensitive.
- Not gated, whatever the setting: `/ping`, `/ready`, `/metrics`, and `/webhooks/gitlab` and `/webhooks/github`, which
  keep their own signature checks.
- michael sends the same header to every specialist, so the token must be the same on every agent.
- The token is read once at start-up. Rotate it by updating the Secret and restarting the pods. A file that is set but
  empty stops the process at start-up.

Limits: there is one shared token and no per-caller identity, so a leaked token gives full access to the two endpoints.
The token does not protect the webhook routes and does not replace keeping `/invocations` off the public ingress.

## Request and webhook size limits

- `SQUAD_MAX_REQUEST_BYTES` (default `1000000`) caps an `/invocations` body. A larger body, declared or chunked, gets `413`
  before it is parsed.
- `SQUAD_MAX_WEBHOOK_BYTES` (default `1048576`) caps a webhook body. The limit is applied before the signature is checked, so
  an oversized delivery is refused without being read.

## Webhook single-flight

michael allows one in-flight run per change request and head. A second delivery for the same key is answered with an
"already in flight" reply instead of starting a run. The claim lives in the session store: the in-process store by default,
and Redis when `SESSION_STORE_URL` is set. Use Redis before running more than one replica. The in-process store holds
at most 10,000 entries and evicts the least recently used one when full, so a busy process can evict a live claim. A
claim that is evicted can let a second run start for the same head.

## Repository and configuration controls

- `security.accepted_risks` is organisation-only. A repository file or a registry entry that sets it is rejected as a
  whole. A scoped risk (`package`, `path`) matches only the findings it names.
- `implementer.allowed_protected_paths` is organisation-only. A repository can add `implementer.protected_paths`, but cannot
  allow a protected path.
- `trigger.allowed_assigners` may only shrink from a lower layer, and an empty list means nobody can start pam from an issue.
- `trigger.skip_bot_authors` defaults to `false`. The bot's own events are always ignored, so the default is safe. Set it to
  `true` only to skip other bots as well.
- `posting.force_dry_run: true` in the organisation file stops every external write on the next invocation. It takes effect
  without a restart. If the organisation file fails validation, the last good file is used, but a `force_dry_run: true`
  line in the broken file is still honoured.

## pam controls

- pam refuses to run without the Kubernetes sandbox (`SANDBOX_NAMESPACE`) unless `ALLOW_LOCAL_SANDBOX=1` is set. The local
  process sandbox is for development only.
- Read-capable git options are refused, and npm runs with a sandbox-controlled user configuration.

## Known defects that affect security

These are defects and gaps in the version documented here. The owners should fix them before production use. They are also
listed in the [handoff](../HANDOFF.md#known-limitations).

| # | Defect | Effect | Workaround |
| --- | --- | --- | --- |
| D2 | With `SANDBOX_NAMESPACE` unset, pam uses the local process sandbox. The chart's `minimal-kind.yaml` turns the sandbox off. | Repository commands run in the pam container without isolation. | Keep `sandbox.enabled: true` outside disposable clusters. |
| D3 | `SQUAD_ALLOW_UNAUTHENTICATED=1` opens `/invocations` and `/jobs/{id}` without a token. | Any caller that reaches the Service can start reviews, and can publish with `post: true` unless the organisation forces dry run. | Use the flag only in disposable demos; set `api.tokenSecret` otherwise; keep the network controls; `posting.force_dry_run` in the organisation file. |
| D6 | The Secret is mounted whole into every agent pod. | A compromised agent can read every secret key. | Split Secrets by agent (planned); keep the number of keys small. |
| D7 | The TTL of sandbox pods is stored but not applied. | A crashed run can leave a pod until its deadline. | Keep `activeDeadlineSeconds` short; check for orphaned pods. |
| D9 | The gateway key comes from `LLM_API_KEY` or `LLM_API_KEY_FILE`. The former `llm.api_key_secret` key was removed from the schema. | Operators may look for a control that does not exist. | Use the keys in [Configuration reference](../reference/configuration.md). |

## Reporting a vulnerability

Report a suspected vulnerability privately, not in a public issue or change request. The preferred channel is GitHub's
private vulnerability reporting, described in [SECURITY.md](https://github.com/acarmisc/the-office-ai-squad/blob/main/SECURITY.md).
If that is not possible, contact the platform team that owns this deployment. Include the version or commit, the configuration that matters (with secrets removed), the steps to reproduce, and
the expected and actual behaviour. Do not include real tokens or customer data in the report. The team acknowledges a report,
assesses it against the threat model, and records the decision in an ADR when the fix changes a control.
