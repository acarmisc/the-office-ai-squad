# Operations runbook

This runbook is for the people who run the squad: dashboards, alerts, the metric and log vocabulary, cost tracking, the common
failures and their fixes, how to replay an invocation without writing anything, and what to do during an incident.

## Dashboards

`deploy/observability/grafana-dashboard.json` defines the dashboard **Code Squad overview** (uid `code-squad-overview`) with an
`agent` variable. Its panels:

| Panel | Query basis | Use it to see |
| --- | --- | --- |
| Invocations by agent and status | `squad_invocations_total` rate | Volume and failures per agent |
| Invocation latency p50 and p95 | `squad_invocation_seconds` histogram | Slow agents |
| Iterations per invocation | `squad_iterations` histogram | Runs that approach their turn limit |
| Findings by severity | `squad_findings_total` increase | What the squad is reporting |
| Tokens by kind | `squad_tokens_total` rate | Model usage (input and output) |
| Tool calls by tool class | `squad_tool_calls_total` rate | Read, local mutation and external write activity |
| Dry-run invocations (24h) | `squad_dry_run_total` increase | External writes refused by dry run |
| VCS errors by provider and operation | `squad_vcs_errors_total` rate | Final VCS request failures; see the metric glossary |
| Config reload failures (1h) | `squad_config_reload_failures_total` increase | Broken organisation or registry files |
| CVE cache hits | `squad_cve_cache_hits_total` rate | Advisory cache effectiveness |

## Alerts

`deploy/observability/prometheus-rules.yaml` defines a `PrometheusRule` named `code-squad-alerts`. Load it into the namespace your
Prometheus operator selects (the file's label `release: kube-prometheus-stack` must match your rule selector). Thresholds are starting
points; tune them with a baseline.

| Alert | Condition | Severity | First action |
| --- | --- | --- | --- |
| `CodeSquadHighFailureRatio` | More than 20% of an agent's invocations fail, for 15 minutes | critical | Check the agent logs and the LLM gateway (see "Gateway down"). |
| `CodeSquadManyIncomplete` | More than 30% of invocations end `incomplete`, for 30 minutes | warning | Check limits (iterations, deadlines, timeouts) and recent prompt or model changes. |
| `CodeSquadHighInvocationP95` | p95 latency above 300 seconds, for 15 minutes | warning | Check the gateway, specialist timeouts and sandbox deadlines. |
| `CodeSquadNoMichaelInvocations` | No michael invocations for one hour | info | Expected outside working hours or without webhooks. Check the webhook setup if it is unexpected. |
| `CodeSquadConfigReloadFailures` | Any reload failure in 15 minutes | warning | Validate the mounted files with `squad config validate`. The last good config stays active. |
| `CodeSquadVcsErrors` | Sustained VCS errors for 10 minutes | warning | Check the VCS token, the rate limit and the host reachability. The logs and result `warnings` name the failing call. |

### Known gaps in the alerts

- The dashboard panel for `squad_dry_run_total` and the alert set do not cover the webhook gateway's rejections (401, 503). Those
  appear only in the HTTP status and in the logs of michael.

## Metrics glossary

Names are the exact exposition names. Prometheus adds `_total` to counters and `_bucket`, `_sum` and `_count` to histograms.

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `squad_invocations_total` | counter | `agent`, `status` (`complete`, `incomplete`, `failed`) | Finished invocations. |
| `squad_invocation_seconds` | histogram | `agent` | Wall-clock duration of an invocation. |
| `squad_iterations` | histogram | `agent` | Model turns per invocation. Buckets 1 to 55. |
| `squad_tokens_total` | counter | `agent`, `kind` (`input`, `output`) | Model tokens. |
| `squad_tool_calls_total` | counter | `agent`, `tool`, `tool_class` (`read`, `local_mutation`, `external_write`) | Tool calls, by the policy class. Unclassified names are never labels. |
| `squad_findings_total` | counter | `agent`, `severity` | Findings produced, before publication limits. |
| `squad_dry_run_total` | counter | `agent` | External write attempts refused by dry run. |
| `squad_cve_cache_hits_total` | counter | none | Advisory cache hits. |
| `squad_config_reload_failures_total` | counter | none | Rejected configuration reloads. |
| `squad_vcs_errors_total` | counter | `provider`, `operation` | VCS requests that failed for good: after the retries, or a transport error. Also counts 4xx and 5xx responses raised as VCS errors. A 404 is not counted. `provider` is `gitlab`, `github` or `jira`. `operation` is the HTTP method and the first API resource, for example `GET repos` or `POST projects`. |

Metrics are served on `GET /metrics` of every agent. Michael's webhook outcomes are not counted separately.

## Logs

Logs are JSON lines on stderr. Each entry has `ts`, `level`, `logger` and `msg`. These fields appear when the event has them:
`agent`, `status`, `duration_ms`, `iterations`, `tool`, `invocation_id`.

The log does not contain prompts, diffs, comments, tokens or secrets. Use `invocation_id` to join the log line with the result,
and the result's `stats.config_hash` to tie it to the configuration that produced it. Typical messages: `invocation finished`,
`webhook job finished`, `webhook job failed`, `agent failed to load`, and the configuration reload warnings.

Set `LOG_LEVEL` to `DEBUG` only for a short investigation. The configuration key `observability.log_level` is not applied; the
environment variable is.

## Cost tracking

Every model call carries LiteLLM metadata tags: `squad:code-squad`, `agent:<id>`, `project:<project>` when the request names a
project, and any `litellm_tags` the caller added (at most 20, each `key:value`). In the gateway, group spend by these tags.

The squad's own cost fields are weaker than the gateway's: `stats.input_tokens` and `stats.output_tokens` are reported per result,
and `stats.cost_hint` is never set in this version. `llm.budget_usd_per_day` is declared but not enforced. For a hard cap, use the
gateway's budgets keyed on the `project:` tag. See [recipe 9](../configuration/recipes.md#9-per-project-llm-budget).

## Common failures and fixes

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Invocations fail with the exception type in `warnings` (for example a connection error) and `status: failed` | LLM gateway down or unreachable from the pod | Check the gateway health and the NetworkPolicy allow-list (`llmGatewayCIDRs`). Check `LLM_BASE_URL`. |
| Many `incomplete` results with an iteration-limit warning | Turn limit reached before `finish` | Look at the change size and the prompt. Raise `agents.<id>.max_iterations` within `limits.max_iterations`, or split the change. |
| Gateway returns rate-limit errors | Too many concurrent reviews | Lower `routing.fan_out_concurrency`, enable the debounce (`trigger.debounce_seconds`), and ask the gateway team for a higher limit. |
| Webhook returns `404` | `webhooks.<provider>.enabled` is false, so `WEBHOOK_PROVIDERS` does not name the provider | Set it on michael (see [Helm](../deployment/helm.md#webhooks)). |
| Webhook returns `401` | Signing secret mismatch | Re-enter the stored secret; check for whitespace (see [GitLab webhook setup](../vcs/gitlab.md) for how each source trims). |
| Webhook returns `503` | Organisation file invalid | Validate the mounted `squad.yaml`; fix and redeliver. |
| Webhook returns `202` but no review appears | `vcs.bot_username` missing, draft, skip label, WIP title, or commenter not allowed | Read the `reason` in the response body and fix the cause. |
| Stale or invalid config warnings | A repository file breaks a rule, or a registry entry names an unknown profile | Run `squad config explain <project> --repo-config <file>`; the rejected layer is listed. |
| Config reload failure alert | Broken `squad.yaml` or `projects.yaml` after an edit | The last good config stays active. Validate the files and fix them. |
| Sandbox pod stuck in `Pending` or `ContainerCreating` | Image pull failure, quota, or a Pod Security rejection | `kubectl describe pod` in the sandbox namespace. Check the image name, the pull secret and the namespace label. |
| pam halts with `incomplete` and "loop detected" | The same failing command repeated three times | Read the failing command and its first error line in the result. Fix the repository or the task. |
| Advisory source unreachable (dwight findings marked unverified) | Egress blocked or the source is down | Check `networkPolicy.advisoryCIDRs` or the proxy. Switch the source off if it is permanently unavailable. |
| Duplicate comments on a change request | Marker missing (an edited comment), or a second squad publishing | Check that every finding comment keeps its `<!-- code-squad:<id> -->` marker. Check `routing.specialists_post` is false. |
| Trace export errors | `OTEL_EXPORTER_OTLP_ENDPOINT` unreachable | Check the collector and `networkPolicy.otlpCIDRs`. The service keeps running without traces. |

## Replay an invocation in dry run

Replay a past request without writing anything:

1. Take the original request body from the caller's logs or from the job record (`GET /jobs/<id>` for asynchronous runs).
2. Set `"post": false` and send it to the same agent. Use the same `project` and `target`.
3. Compare `stats.config_hash` with the original result. A different hash means the configuration changed since then.
4. Compare the head sha in the findings. A different head means the change moved; the findings anchor to the new head.

For a webhook event, re-create the delivery with the same body and a new `X-GitHub-Delivery` or `X-Gitlab-Event-UUID` value, sign
it with the stored secret, and send it to the webhook path. A repeated delivery id is answered as a duplicate, so use a new id.
Webhook replays are not dry runs: the gateway requests publication. Force dry run in the organisation file first, or replay with
`/invocations` and `post: false`.

## Incident checklist

1. **Scope.** Which agents, which projects, since when. Check `squad_invocations_total` by `agent` and `status`.
2. **Stop the bleeding if writes are wrong.** Set `posting.force_dry_run: true` in the organisation file and reload (or redeploy).
   This stops external writes for every project. Scale michael to zero only if the webhook path itself is the problem.
3. **Find the cause.** Read the `warnings` of two or three affected results, the logs for the `invocation_id`, and the
   `config_hash`.
4. **Check the dependencies.** Gateway, VCS API, advisory sources, Kubernetes API, sandbox namespace.
5. **Fix and verify.** Apply the fix, then run a dry run for one affected change request.
6. **Clean up.** Remove duplicate comments or stale statuses by re-running the review for the change request. Each run replaces
   the summary and the status of its context; inline comments with markers are not repeated.
7. **Record.** Write the timeline, the cause and the follow-up in the team's incident record. If the fix changes a control, record
   an ADR.
