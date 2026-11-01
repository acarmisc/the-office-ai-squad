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

## Known defects that affect security

These are defects and gaps in the version documented here. The owners should fix them before production use. They are also
listed in the [handoff](../HANDOFF.md#known-limitations).

| # | Defect | Effect | Workaround |
| --- | --- | --- | --- |
| D1 | The chart does not set `WEBHOOK_PROVIDERS`. | Webhook routes are not registered, so the exposed paths return `404`. Not a bypass, but a broken control path that someone may "fix" by widening the ingress. | Set `agents.michael.env` as shown in [Helm](../deployment/helm.md). |
| D2 | With `SANDBOX_NAMESPACE` unset, pam uses the local process sandbox. The chart's `minimal-kind.yaml` turns the sandbox off. | Repository commands run in the pam container without isolation. | Keep `sandbox.enabled: true` outside disposable clusters. |
| D3 | `/invocations` has no authentication in the application. | Any caller that reaches the Service can start reviews, and can publish with `post: true` unless the organisation forces dry run. | Network controls; `posting.force_dry_run` in the organisation file. |
| D4 | The image does not install the `redis` extra, and `RedisSessionStore` imports `redis` when it is built. | Setting `SESSION_STORE_URL` to a Redis URL fails at start-up. The Helm `sessionStore.url` has the same effect. | Leave the store in memory, or build an image with the extra. |
| D5 | `squad_vcs_errors_total` is declared but never incremented. | The `CodeSquadVcsErrors` alert cannot fire. | Watch the warnings in results and the pod logs for VCS errors. |
| D6 | The Secret is mounted whole into every agent pod. | A compromised agent can read every secret key. | Split Secrets by agent (planned); keep the number of keys small. |
| D7 | The TTL of sandbox pods is stored but not applied. | A crashed run can leave a pod until its deadline. | Keep `activeDeadlineSeconds` short; check for orphaned pods. |
| D8 | `security.accepted_risks` can be added by a repository layer. | A repository can accept an advisory for its own change. | Restrict the field to the organisation layer (open point, ADR 0009). |
| D9 | The chart and examples name keys the code does not read: `ops.namespaces`, the `llm` alias map, `github-app-id` in the Secret sample, `llm.api_key_secret`. | Operators may believe a control is configured when it is not. | Use the keys in [Configuration reference](../reference/configuration.md). |

## Reporting a vulnerability

Report a suspected vulnerability privately to the platform team that owns this repository, not in a public issue or change
request. Include the version or commit, the configuration that matters (with secrets removed), the steps to reproduce, and
the expected and actual behaviour. Do not include real tokens or customer data in the report. The team acknowledges a report,
assesses it against the threat model, and records the decision in an ADR when the fix changes a control.
