# 0008 — Per-invocation services, fail-closed configuration and knowledge lookup order

- Status: accepted
- Date: 2026-11-01

## Context

Reviewers need the effective configuration, a VCS provider, repository skills and the
publish policy for each request. The brief (4.8, 6) requires that the repository layer
of `.squad/config.yml` is read from the target branch, that the org `force_dry_run`
setting can never be overridden, and that an invocation with no project still works.

## Decision

- `_common/services.py` builds the `services` dict once per request (`ServiceBuilder`).
  Each step degrades on its own and records a warning in `config_warnings`. A missing
  project, VCS or repository file leaves that service out.
- Configuration is resolved in two passes. The first pass (org, registry, bootstrap
  entry, call layer) gives the VCS settings. The provider then reads
  `.squad/config.yml` from the target branch and the second pass adds the repository
  layer. The provider of the run is not replaced by the second pass.
- An invalid org configuration fails closed: `posting_allowed` is false and the run is
  dry-run, with a warning. `force_dry_run` is applied the same way, as an AND with the
  request's `post`.
- `plan_run` applies agent settings to the spec with `dataclasses.replace`. The
  disabled-agent path returns `incomplete` before any model call. `tool_allowlist` is
  intersected with the spec's tools, and `finish` is always kept so that a run can end.
- `read_knowledge` searches the agent's own pack, then the shared pack in
  `code_squad/_common`, then `knowledge_extra_dirs` from configuration. A resolved path
  must stay inside its pack, which blocks symlink escapes.
- The repository skills are read from the base commit (the CR's `base_sha`), so the skill
  cache can key on a SHA.

## Consequences

- A run without a project behaves as before: it has defaults, payload skills and no
  VCS. Existing tests and the CLI are unaffected.
- The shared React pack is visible to every agent, not only to jim and pam. Its topics
  appear in the "available topics" list of every agent.
- `tool_allowlist` cannot remove `finish`. The limit is in the design, not in the schema.
- Not yet enforced at run time: the per-agent `budgets` (tokens, wall clock, tool calls),
  `fallback_model` on overload, `disabled_rules`, `severity_overrides` and the
  `review.suppressions_enabled` and `review.summary_template` settings. Open for review.
- The repository layer can select a different allowed credential name through
  `vcs.auth.token_secret`, because that field has no tighten-only rule (see ADR 0003).
  Open for review.
