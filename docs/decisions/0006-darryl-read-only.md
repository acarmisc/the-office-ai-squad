# 0006 — darryl is read-only by construction

- Status: accepted
- Date: 2026-11-01

## Context

`darryl` reviews pipelines and manifests, and troubleshoots production symptoms. The
troubleshooting path needs cluster state, logs, events, metrics and CI history. Those
sources hold secrets: pod environment values, ConfigMap contents, log lines that echo
tokens. A troubleshooting agent that can also change the cluster turns a prompt
injection in a log line into an outage. BRIEF §8 and §4.4 require strictly read-only
troubleshooting, and the Helm chart must grant read-only RBAC.

## Decision

- **No mutation tools exist.** The `darryl` tool set is classified `READ`, except
  `publish_review`, which is the only `EXTERNAL_WRITE` tool and posts review comments.
  Remediation is advice in `finish()` output. A test scans the `darryl` source for
  create, patch, replace, delete and connect calls, and fails on any match.
- **Kubernetes access is read-only at two levels.** RBAC grants `get`, `list` and `watch`
  on the listed resources (including `pods/log`) only, with no `secrets` rule, per
  namespace from `devops.allowedNamespaces` (or one read-only ClusterRole when
  `devops.clusterWide` is set). The client code adds a namespace
  allow-list (`ops.allowed_namespaces`, empty means nothing is readable) and refuses
  any kind containing `secret`.
- **Secret values never reach the model.** Pod `env` values are replaced by
  `<redacted>` (names and `valueFrom` references are kept). ConfigMap values pass
  through the redactor. The `last-applied-configuration` annotation is never returned, because it can carry
  env values.
- **Every output is redacted and bounded.** `redact()` masks tokens, keys, passwords,
  connection-string credentials and, optionally, e-mail addresses, plus any configured
  extra patterns. Output is capped and then wrapped as untrusted content. Invalid
  redaction configuration withholds the output rather than passing it through.
- **Publishing is limited to review mode.** `publish_review` refuses in troubleshoot
  mode, and the posting gate still applies in review mode, so `post: false` stops it.
- **Observability backends are opt-in.** Prometheus and Loki are used only when a URL
  is configured. Argo CD and Alertmanager are stubs. Each backend result is capped in
  series count, samples and lines.

## Consequences

- darryl cannot fix an incident. It can show the evidence, rank hypotheses and write
  the remediation for a human to apply. This is intended.
- A compromised or misled model can read at most the allow-listed namespaces, and
  the values it reads are masked. Residual risk: names of workloads, images and
  environment variable names are visible; event and log text is visible after
  redaction, so redaction gaps remain a residual risk (see `docs/security/` when it
  is written).
- Adding a write capability later requires a new ADR, a new tool class and a RBAC
  change. It cannot be done by configuration alone.
- The VCS interface has no operation to list merged change requests. "What changed
  before the incident" therefore uses CI runs on the default branch, and the window is
  not applied because CI runs carry no timestamps. This is recorded in the tool output.
