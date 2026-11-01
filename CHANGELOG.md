# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/) for the application and the chart.

## Unreleased — operational readiness

Decision record: [ADR 0013](docs/decisions/0013-operational-readiness.md). Fixes from the adversarial review, applied before the
first operational test.

### Fixed

- **Publication.** One pipeline for every agent, including michael. The verdict is computed over every schema-valid finding.
  Binary files are listed as not reviewed without capping the verdict; truncated text files still cap it at `comment`. A
  specialist failure with a blocker gives `request_changes` with an incomplete warning. Only added lines are anchored inline.
  Markers are matched only on comments written by the bot. Model markdown is neutralised (quick actions, mentions, images, links).
- **Dry run.** `posting.force_dry_run` is read on each invocation, so it takes effect without a restart. If the organisation
  file fails validation, the last good file is used, and a `force_dry_run: true` line in the broken file is still honoured.
- **Configuration notes.** Config warnings, rejected layers and invalid organisation notices appear in a "Configuration notes"
  section of every published summary.
- **Accepted risks.** `security.accepted_risks` is organisation-only and applied before publication. A `package` or `path` scope
  is honoured by dwight's guard, so a scoped risk does not hide a finding for another package.
- **API.** `/invocations` and `/jobs/{id}` refuse every request without a token, unless `SQUAD_ALLOW_UNAUTHENTICATED=1` is set.
  Request and webhook bodies have size limits; the webhook limit applies before the signature check. Repeated runs with the
  same key return the stored result, and an in-flight run returns `409`. Caller tags in the `squad:`, `project:` and `agent:`
  namespaces are dropped.
- **Single flight.** The webhook gateway shares the session store with the server, so a Redis store also serialises webhook
  runs. An empty in-process store is no longer replaced by a default one.
- **Runs.** A hard per-run token ceiling (`limits.max_run_tokens`), per-agent wall-clock and tool-call budgets, `fallback_model`
  on gateway 429 and 5xx, and job failures log the exception type.
- **pam and darryl.** pam refuses to run without the Kubernetes sandbox unless `ALLOW_LOCAL_SANDBOX=1`. Read-capable git options
  are refused. Protected paths can be allowed only by configuration. Issue triggers need an allowed assigner. darryl redaction
  covers secret-named environment pairs, JSON name and value pairs and common token formats.
- **Chart.** `api.allowUnauthenticated` (default `false`) renders `SQUAD_ALLOW_UNAUTHENTICATED=1` only when true. More than one
  michael replica is refused while `sessionStore.url` is unset.

### Removed

- Configuration keys with no run-time effect: `review.summary_template`, `review.chunking`, `review.suppressions_enabled`,
  `review.baseline_file`, `review.verdict.request_changes_on_blocker`, `agents.*.disabled_rules`, `severity_overrides`, `language`,
  `agents.*.budgets.tokens`, `cost_hint_usd`, `trigger.slash_commands`, `vcs.status_mode`, `llm.tag_template`, `llm.aliases`,
  `llm.budget_usd_per_day`, `llm.api_key_secret`, `observability.*` (sampling, content capture, log level, OTLP endpoint),
  `ops.incident_window_minutes`, `security.local_scanners`, `limits.max_tool_calls` and the `.squad/baseline.yml` file.
- `config/reload.py`, the operation journal, `safe_retry.py` and the baseline loader.
- Helm: the `vcs.status_mode` value in the example files.

### Added

- `docs/operations/first-operational-test.md`: the procedure, acceptance criteria and results table for one real project.
- `deploy/helm/code-squad/values-examples/operational-test.yaml`: dry-run values for michael, jim, angela, dwight and darryl.
- `scripts/trial_review.sh` and `scripts/trial_report.py`: one dry-run or posting review, reported with tokens and wall time.
- Environment variables in the bootstrap table: `SQUAD_ALLOW_UNAUTHENTICATED`, `SQUAD_MAX_REQUEST_BYTES`, `SQUAD_MAX_WEBHOOK_BYTES`,
  `ALLOW_LOCAL_SANDBOX` and `SQUAD_DOCS_URL`.

## [0.1.0] - unreleased

First complete version, built milestone by milestone (see `STATUS.md`).

### Added

- **Platform (M0 to M4).** Agent specification and registry, contract models with `extra="forbid"`, fail-closed validation, tool
  policy with classes, posting gate, untrusted-content wrapping, runtime with one retry, `finish` validation and iteration limits,
  FastAPI server with `/ping`, `/ready`, `/metrics`, `/invocations` and `/jobs/{id}`.
- **VCS and findings (M2).** GitLab and GitHub providers (GitHub App and token authentication), the `VcsProvider` protocol with
  capability flags, the shared conformance suite, anchoring, deduplication, idempotent publication and webhook verification.
- **Configuration (M3).** Five layers, tighten-only and org-only merge rules, the project registry with glob matching and profiles,
  repository files from the target branch, hot reload with a safe fallback, provenance, and the `squad config` commands.
- **Skills (M4).** Discovery in `.agents/skills`, `.claude/skills` and `.squad/skills`, precedence, limits, base-branch reading,
  `load_skill`, caching and sanitising.
- **Reviewers (M5 and M6).** `jim` (React), `angela` (Java) and `dwight` (security), with knowledge packs, dependency parsers for the
  supported lockfiles, vulnerability clients with caching and back-off, and the offline verdict guard.
- **DevOps and sandbox (M7 and M8).** `darryl` with review and read-only troubleshooting tools, redaction, namespace allow-lists and a
  Prometheus adapter. `pam` with advisor and implementer modes, the Kubernetes and local sandboxes, a command allow-list and a
  trajectory monitor.
- **Orchestrator (M9).** `michael` with routing, risk tiers, parallel fan-out with timeouts and circuit breakers, aggregation and one
  consolidated publication, and webhook handling for GitLab and GitHub.
- **Packaging (M10).** Container image for all agents, Helm chart with NetworkPolicies, RBAC, ingress for webhooks only and example values,
  Docker Compose with an offline fake LLM, kind scripts and the HTTP smoke test.
- **Documentation and examples (M11).** The documentation set with generated reference pages and validated examples, GitLab and GitHub
  examples, the Backstage catalogue, the image bump script, and the evaluation harness with replay cases.

### Notes

- Known limitations are listed in `docs/HANDOFF.md`. Two of them need attention before production: `/invocations` is open unless
  `SQUAD_API_TOKEN` is set, and the sandbox falls back to a local process when no sandbox namespace is set.
- The Helm chart sets `WEBHOOK_PROVIDERS` on michael from `webhooks.*.enabled`, so the webhook routes are registered by default.
- The container image installs the `redis` extra, so a Redis `SESSION_STORE_URL` starts. Job state is still per replica.
- `squad_vcs_errors_total` counts final VCS failures per provider and operation. A 404 is not counted.
