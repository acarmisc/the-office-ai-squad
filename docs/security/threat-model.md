# Threat model

This model covers the squad as shipped: six agents in one image, a Kubernetes deployment, and two kinds of external
input (VCS events and repository content). It lists what the squad protects, who might attack it, where the trust
boundaries are, which controls apply, and what remains. The boundaries are drawn in
[Architecture overview](../architecture/overview.md#trust-boundaries).

## Assets

| Asset | Why it matters | Where it lives |
| --- | --- | --- |
| VCS credentials (project tokens, GitHub App private key) | Allow the squad to read code and to write comments, statuses and branches | Secret files under `/var/run/secrets/squad` in every agent pod |
| LLM gateway key | Spend and access to the model gateway | Environment variable `LLM_API_KEY`, from the Secret |
| Webhook signing secrets | Anyone holding them can forge deliveries | Secret, mounted on michael |
| Repository code and change content | Confidential source and unreleased changes | Read into agent context; sandbox workspace for pam |
| Cluster state read by darryl | Names, events, logs, config maps | Tool results, redacted, in the model context |
| Integrity of verdicts and statuses | Reviewers and merge gates rely on them | Commit statuses and summaries on change requests |
| Sandbox pods | Run repository code | Sandbox namespace |

Assets that the squad does not hold: merge rights, cluster write rights, customer data outside the repository.

## Adversaries

| Adversary | Capability | Typical goal |
| --- | --- | --- |
| External attacker without a VCS account | Sends HTTP to the public webhook path | Trigger work, flood the queue, probe the gateway |
| Contributor or fork author | Writes diffs, comments, description, skills in a change request | Get a bad change approved, leak secrets through output, make the model ignore a finding, make pam run code |
| Compromised repository dependency or script | Runs code inside the sandbox | Reach secrets, exfiltrate source, pivot to the cluster |
| Hostile advisory or log text | Content the squad reads from third parties | Steer the model, hide a finding |
| A caller inside the network | Reaches `/invocations` on a Service | Start reviews, or publish with `post: true`, without any identity |
| A user with a comment on a change request | Writes a `/squad` command or an `@bot` mention | Start a run, if allowed |
| Operator error | Misconfigures values, secrets or policy | Expose a path, disable a control, widen egress |

## Threats and controls

| # | Threat | Control | Status |
| --- | --- | --- | --- |
| T1 | Forged webhook delivery | Signature check (GitLab token, GitHub HMAC over the raw body, constant-time compare), `401` on failure | In place |
| T2 | Replayed delivery | Delivery-id de-duplication after a final outcome; one in-flight run per change request and head, shared through the session store | In place; de-duplication is per replica unless Redis is configured |
| T3 | Bot-loop: squad reacting to its own events | `vcs.bot_username` required; own-author events ignored | In place; a project without it is ignored |
| T4 | Unauthorised commenter starts a run | `trigger.allowed_commenters` (empty means nobody) | In place |
| T5 | Unauthenticated caller on `/invocations` | Shared bearer token (`SQUAD_API_TOKEN`, constant-time compare) required; with no token the endpoints refuse every request (fail closed); not routed by the ingress; network policies and the Service | **Residual**: one shared token with no caller identity; open only when an operator sets `SQUAD_ALLOW_UNAUTHENTICATED=1` |
| T6 | `post: true` from an untrusted caller publishes | Organisation `posting.force_dry_run` overrides every request | In place when set; off by default |
| T7 | Prompt injection through the diff, description, comments, files, logs, skills, advisories | Untrusted wrapping with random delimiters, rule in every prompt, deterministic verdict rules, guards, specialists do not publish by default | In place; model reasoning can still be swayed. See [Prompt injection](prompt-injection.md) |
| T8 | A change edits its own review rules | Skills and repository config are read from the target branch; the head is an org opt-in with a warning | In place |
| T9 | A change lowers its own review thresholds | Tighten-only and org-only rules; whole-layer rejection | In place |
| T10 | Secret leaked into a comment or summary | Redaction in darryl; token masking in pam output; security reviewer reports location only; secret-scan in CI | Partial: detection is by pattern and by the model |
| T11 | Secret read from a cluster | No secret RBAC; secret kind refused; env values replaced | In place for the API; config maps are readable (see RBAC) |
| T12 | darryl changes a cluster | No mutation tools; read-only RBAC; a test scans the source | In place |
| T13 | Repository code exfiltrates secrets from the sandbox | No secrets in the sandbox environment; scoped credentials in an askpass file; no service account token; egress allow-list | In place; code can still read its own checkout |
| T14 | Sandbox escape into the node | Non-root uid 10002, read-only root, dropped capabilities, `RuntimeDefault` seccomp, restricted namespace | In place with a conformant runtime; the local backend has no isolation |
| T15 | Sandbox pod outlives its run | Deadline, `finally` destruction | Partial: TTL is not applied; a crashed agent can leave a pod until its deadline |
| T16 | pam pushes to a protected branch or force-pushes | Refusals in `start_work` and `push_branch`; no force refspecs | In place |
| T17 | pam changes CI, lockfiles or dependencies unnoticed | Protected-path refusal unless `"allow"`; listed in the change request | In place; the reviewer decides |
| T18 | Merge without a human | No merge capability; approval only when configured | In place |
| T19 | Advisory data missing, verdict approves anyway | Unverified marking, guard, publish-time cap | In place |
| T20 | Egress to unexpected hosts | Advisory host allow-list (organisation only), NetworkPolicy allow-lists, proxy option | In place when policies are enforced |
| T21 | Config from an untrusted source | Only the platform writes the organisation file and the registry; the repository file is restricted; accepted risks and protected-path allowances are organisation-only | In place |
| T22 | Oversized or hostile input exhausts resources | Request and webhook body limits (the webhook limit is applied before signature checks); output caps; per-run token ceiling (`limits.max_run_tokens`); tool-call and wall-clock budgets; per-request timeouts | In place; there is no global rate limit |
| T23 | Telemetry leaks content | Logs carry metadata only; span attributes are an allow-list; job failures log the exception type, not the message | In place |

## Residual risks

1. **Unauthenticated `/invocations`** (T5). Only an explicit `SQUAD_ALLOW_UNAUTHENTICATED=1` opens the endpoints. Then any pod
   that can reach the Service can start a review, and with `post: true` and no `force_dry_run` it can publish. Set `api.tokenSecret`, mitigate with network policy, and put
   authentication in front of any external route (see [Ingress and webhooks](../deployment/ingress-webhooks.md)).
2. **Shared Secret.** Every agent pod can read every key in the Secret, so a compromised agent can read the VCS tokens
   and the webhook secrets.
3. **Model judgement.** The model may miss a defect, invent one, or be steered by content it reads. Verdict rules and
   guards limit the effect; they do not make the model reliable.
4. **Repository code in the sandbox** can run anything that its own scripts run, and it can consume its quota until the
   deadline.
5. **Local sandbox fallback.** When `SANDBOX_NAMESPACE` is unset, pam runs repository commands in its own container.
   The kind example does this.
6. **Advisory coverage gaps.** Packages without a feed, and Dockerfile base images, are unverified by design.
7. **Config maps are readable** by darryl's RBAC, and their values reach the model after redaction.
8. **In-memory state.** Job state and de-duplication are per replica unless `SESSION_STORE_URL` is set. The in-process store
   holds 10,000 entries and can evict a live in-flight claim, so use Redis for any production deployment. A replica restart
   loses in-flight jobs.
9. **Accepted but not wired.** Configuration keys that were not applied at run time were removed from the schema in ADR 0013.
   The remaining declared-but-unapplied keys are listed in the [handoff](../HANDOFF.md).
10. **No extra CA or identity layer.** Private certificate authorities and an identity provider in front of the squad are
    deployment work, not features of the platform.

## Data retention

- Source code and model outputs are not stored beyond the invocation, except for the in-memory job result until the
  process restarts, and the optional session store when `SESSION_STORE_URL` is set. The Redis path is not usable in the
  current image (see [Hardening](hardening.md#known-defects-that-affect-security)).
- Advisory data is cached in memory per run. The NVD rate window is per run.
- Logs are structured metadata with the invocation id, agent, status, duration and iterations. Their retention is the
  platform's log retention.
- Sandbox pods are destroyed after each invocation. Their workspace is an `emptyDir`, removed with the pod.
- Change requests and comments are stored by the VCS host under its own retention.

## Out of scope

Compromise of the Kubernetes control plane, the container runtime, the VCS host, the model gateway, and the LLM
provider. Denial of service through the VCS host's own limits. Social engineering of the reviewers.
