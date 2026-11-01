# 0013 — Operational readiness after the adversarial review

- Status: accepted
- Date: 2026-11-01

## Context

An adversarial review of `main` (findings ADV-01 … ADV-23) reproduced several defects that
the green test suite did not catch: a dry-run bypass through `routing.specialists_post`, a
fail-open verdict when findings were dropped before publication, a local sandbox that
exposes the pod's secrets, unwrapped change-request metadata, unsanitised comment markdown
(GitLab quick actions), marker spoofing, GitLab anchoring on context lines, dead
idempotency code and per-invocation intel caches. The architect and the reviewer debated
priorities for a first operational test on one real repository (dry-run first, then
posting; webhooks and pam off).

## Decision

Fix before the first operational test, each with a regression test that fails on the
previous code:

- Publication: one pipeline (`findings.publish`) for every agent including michael, with an
  `incomplete` outcome; the verdict is computed over all schema-valid findings; findings
  that cannot be anchored become general notes; `head_sha` comes from the run state; paths
  are normalised; only added lines are anchored inline; per-comment provider errors fall
  back to a general note; markers are matched only on comments authored by the bot;
  model-authored markdown is neutralised (line-leading `/` and `@`, images, links outside
  an allow-list); truncated or binary files are reported as not reviewed and cap the
  verdict at `comment`; when a specialist fails but a blocker exists the verdict is
  `request_changes` with an incomplete warning.
- Dry-run: specialists receive `post = routing.specialists_post AND gate.post_allowed`.
- Untrusted content: every VCS-originated string reaching the model is wrapped; patches
  are sent as raw text, the bot's own comments are not re-sent.
- API: authentication fails closed unless `SQUAD_ALLOW_UNAUTHENTICATED=1`; request and
  webhook body size limits (webhook limit applied before signature verification);
  org-only `project_config` fields return 422; an org-level model allow-list; caller tags
  in the `squad:`, `project:` and `agent:` namespaces are dropped.
- Runs: idempotency by key with in-flight/done states released on failure; at most one
  in-flight run per (project, change request, head); a hard per-run token ceiling;
  `fallback_model` on gateway 429/5xx; tool-call and wall-clock budgets; job store evicts
  on write; job failures log the exception type.
- Configuration: last good org config is kept when a reload fails validation (not when the
  file is unreadable); config warnings and rejected layers appear in the published
  summary; `posting.force_dry_run` takes effect on the next invocation; unenforced keys are
  removed from the schema; `security.accepted_risks` is org/registry-only and applied
  before publication; `trigger.skip_bot_authors` defaults to false (the bot's own events
  are always ignored); `config/reload.py` and the operation journal are removed.
- pam and darryl: pam refuses to run without the Kubernetes sandbox unless
  `ALLOW_LOCAL_SANDBOX=1`; read-capable git options are refused and npm runs with a
  sandbox-controlled user config; protected paths can only be allowed by configuration;
  issue triggers require an allowed assigner; darryl redaction covers secret-named
  environment pairs, JSON name/value pairs and common provider token formats.
- dwight: the intel service is a process singleton keyed by the security config.
- Observability: michael no longer re-counts specialist tokens and findings.
- Chart: more than one michael replica is refused while `SESSION_STORE_URL` is unset.

Deferred until the operational test has produced evidence: live-model evaluation and new
golden cases for dwight, darryl and pam, sharing one review context across specialists,
prompt caching, supersede-cancel of in-flight runs, a persistent job queue.

`/metrics` stays unauthenticated (labels carry no sensitive values; scope it with
NetworkPolicy). The skills hijack filter stays as defence in depth and is not documented
as a security control.

## Consequences

The first operational test runs with webhooks and pam disabled, `ai-review/michael` as a
non-required status, and `posting.force_dry_run` as the rollback switch. Its provider
responses (context lines, renames, multi-line ranges, GitHub App identity) become new
conformance fixtures.
