# darryl: DevOps specialist

`darryl` has two jobs. In **review** mode it checks CI pipelines, container images, IaC and Kubernetes
manifests in a change. In **troubleshoot** mode it investigates a production symptom with read-only
access to the cluster, the CI history and, when configured, metrics and logs. It never changes a
cluster. Remediation is written as advice for a human.

| Item | Value |
| --- | --- |
| Role | devops |
| Modes | `review`, `troubleshoot` |
| Default model | `sonnet-5-5` |
| Max tokens per call | 8192 |
| Max model turns | 30 |
| Writes externally | `publish_review` in review mode only |

## Triggers

- Review: routed by `michael` for `.gitlab-ci.yml`, `.github/workflows/**`, `**/Dockerfile*`,
  `**/*.tf`, `**/Chart.yaml`, `**/values*.yaml`, `deploy/**`, and compose and kustomize files
  (built-in routes).
- Incident: `michael` sends an incident intent to `darryl` in troubleshoot mode when the request
  is in troubleshoot mode, or contains words such as incident, alert, 5xx, down or crashloop. The
  result is returned as is and, when the target is an issue number and posting is allowed, posted as
  an issue comment.

## Tools and policy class

| Tool | Class | Purpose |
| --- | --- | --- |
| `k8s_get` | read | Objects by kind, namespace, name or selector. |
| `k8s_describe` | read | One object with its status and events. |
| `k8s_events` | read | Events in a namespace over a window. |
| `k8s_logs` | read | Container logs, optionally `previous` after a restart. |
| `k8s_top` | read | Pod resource usage. |
| `rollout_history` | read | Revisions of a deployment. |
| `ci_runs` | read | Recent CI runs on a ref. |
| `ci_job_log` | read | The failure region of a CI job log. |
| `prom_query` | read | PromQL instant or range query, when Prometheus is configured. |
| `logs_query` | read | Loki query, when Loki is configured. |
| `deployment_status` | read | Argo CD status. Stub: reports "not configured" in this version. |
| `recent_changes` | read | Recent CI runs on the default branch, as the "what changed" signal. |
| `get_review_context`, `read_file`, `search_repo`, `list_tree` | read | Review mode. |
| `get_project_skills`, `load_skill`, `read_knowledge` | read | Guidance. |
| `publish_review` | external write | Review mode only. Refused in troubleshoot mode and in dry run. |
| `finish` | read | Ends the run. |

There is no tool that creates, patches, deletes or executes into a workload. A test scans the
`darryl` source for such calls and fails on a match ([ADR 0006](../decisions/0006-darryl-read-only.md)).

## Guarantees

- **RBAC.** The chart grants `get`, `list` and `watch` on pods, pod logs, events, services, endpoints,
  config maps, deployments, replica sets, stateful sets, daemon sets, controller revisions and pod
  metrics, per allowed namespace (a Role per namespace) or cluster-wide only when `devops.clusterWide`
  is set. Secrets are never granted. See [RBAC](../deployment/rbac.md).
- **Client checks.** The namespace must be in `ops.allowed_namespaces`; an empty list means nothing is
  readable. Any kind that contains "secret" is refused.
- **Secret values.** Pod environment values are replaced with `<redacted>`; names and references are
  kept. The `last-applied-configuration` annotation is never returned.
- **Redaction.** Every output passes through `redact()`: PEM blocks, authorisation headers, connection
  string credentials, JWTs, token-like values and extra `ops.redaction_patterns`. Invalid redaction
  configuration withholds the output. Output is capped and wrapped as untrusted content.
- **Bounded observability.** Prometheus and Loki results are capped by series count, samples and lines
  (`ops.max_query_points`, `ops.max_log_lines`).

Config maps are readable by RBAC and their values pass through the redactor. Their keys and values
are still visible to the model after redaction. That is a residual risk, listed in the
[threat model](../security/threat-model.md).

## Troubleshooting method

The prompt defines a fixed method, and the result follows it:

1. Restate the symptom and the blast radius. Say what is assumed when a namespace or time is missing.
2. Form two to five ranked hypotheses before reading evidence, one of which explains a partial failure.
3. Gather evidence with read-only tools, starting with recent and cheap queries (workload state,
   events, previous logs, rollout history, CI runs).
4. Mark each hypothesis `confirmed`, `refuted` or `untested`. Confirmation needs evidence that would be
   absent if the hypothesis were false.
5. Conclude with a root cause and its evidence, or with "unknown" and the next checks in order.
6. Propose numbered remediation and a rollback, each with its effect, verification and undo. Name the
   role that should act.
7. List what was not checked.

Observed facts are separated from inference, and a tool error or "not configured" is recorded as a gap,
not as evidence of health.

## Outputs

The smoke-stub output below shows the result shape only. It was produced by the scripted model
of the offline fake LLM, not by an incident. A real troubleshoot result contains the hypotheses
and the evidence list in `summary` and `data`.

```json
{
  "agent": "darryl",
  "status": "complete",
  "verdict": "comment",
  "summary": "Smoke run: DevOps reviewer completed its scripted pass. No findings were raised and nothing was published.",
  "findings": [],
  "stats": {"iterations": 2, "input_tokens": 20, "output_tokens": 10, "tool_calls": {"read_knowledge": 1, "finish": 1}},
  "posted": {"notes": 0, "discussions": 0, "status": null, "urls": []},
  "warnings": []
}
```

## Knowledge

Pack `devops/` with the index `devops/index`. Topics: `devops/gitlab-ci`, `devops/github-actions`,
`devops/dockerfile`, `devops/kubernetes-manifests`, `devops/helm-kustomize`, `devops/terraform`,
`devops/release-safety`, `devops/dora`, `devops/troubleshooting-method`, `devops/k8s-failure-patterns`
(CrashLoopBackOff, OOMKilled, image pull failures, failed rollouts, probe failures, pending pods, DNS,
endpoints, evictions and RBAC denials).

## Configuration that affects darryl

| Key | Default | Effect |
| --- | --- | --- |
| `ops.allowed_namespaces` | `[]` (organisation only) | Namespaces darryl may read. Keep in step with `devops.allowedNamespaces` in the chart. |
| `ops.prometheus_url`, `ops.loki_url`, `ops.argocd_url` | unset (organisation only) | Enable the adapters. Argo CD is a stub. |
| `ops.redaction_patterns` | `[]` | Extra regular expressions to redact (repository layers may add). |
| `ops.max_log_lines` | `500` | Lines per log query. |
| `ops.max_query_points` | `11000` | Points per metrics range query. |
| `agents.darryl.enabled`, `model`, `max_tokens`, `max_iterations` | built-in | As for other agents. |
| `review.*` | see reference | Publication thresholds in review mode. |

## Limits

- Logs and events are the largest source of accidental disclosure. Redaction covers known shapes; an
  unknown secret format can pass.
- The VCS interface cannot list merged change requests, so "what changed" uses CI runs on the default
  branch. The time window is not applied, because CI runs carry no timestamps. The tool output says so.
- Without Prometheus or Loki configured, the tools answer "not configured", and the prompt asks the
  model to record that as a gap.
- Argo CD status is not available.

## Known weaknesses

- The model can be misled by plausible log lines. The method asks for competing hypotheses and an
  explicit "unknown", which reduces but does not remove this risk.
- Root cause claims for intermittent failures depend on the window of evidence the tools return.

## How to evaluate

The eval set does not yet include the troubleshooting scenarios in the brief (CrashLoopBackOff from a
bad variable, OOMKilled, and an image pull failure), so the root-cause score is not measured. The unit
tests cover the read-only guarantees, the redactor, the namespace checks and the fake-cluster
scenarios in `tests/darryl/`. See [Testing](../testing/index.md).
