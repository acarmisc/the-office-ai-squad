# 0003 — Configuration layering, tighten-only rules and hot reload

- Status: accepted
- Date: 2026-10-31

## Context

Onboarding a project, changing a model, a threshold, a routing rule or a template must
not need a code change or an image rebuild (brief 4.8). Configuration also decides
security-relevant behaviour: which hosts are contacted, which credentials are used,
whether writes are enabled, how far budgets stretch. A repository controls its own
`.squad/config.yml`, and a change request can edit that file, so a repository must not
be able to widen what the operator allowed.

## Decision

1. **Five layers, lowest to highest precedence:** built-in defaults; the org file plus
   `SQUAD__SECTION__KEY` variables; the project registry (glob entries and profiles,
   the most specific match last); the repository file read from the target branch; the
   per-call overrides. The schema in `config/schema.py` is the single source of truth
   for defaults, validation, JSON Schema, the reference docs and `squad config explain`.
2. **Merge policy on every field**, declared in the schema (`x-merge`):
   - `free`: any layer may set it.
   - `tighten_only`: a repository or call may only move the value toward stricter. For
     numeric ceilings (budgets, skill limits) that means not above the matching
     `limits.*`. For thresholds, lower. For allow-lists, a subset of the inherited list.
     For booleans and `approve_mode`, not looser than inherited.
   - `org_only`: a repository or call may only restate the value the operator layers
     resolved. Egress hosts, credentials' hosts, sandbox images, `force_dry_run`, the
     secret policy and the platform limits are org-only.
   Lists are replaced by default. Lists marked `x-mergeable-set` are unioned, so a
   repository can add protected paths, sensitive paths, routes and redaction patterns,
   but never remove them.
3. **Whole-layer rejection.** If any setting in a repository or call layer violates
   these rules, or the layer does not validate, the entire layer is dropped. The
   violations are listed in `rejected_layers`, the review summary and the warnings.
   Partial application is never done, because a partly applied file is hard to reason
   about and easy to exploit. Invalid YAML is a warning, and the layer is ignored.
4. **Floor rules** (`SEC-SECRETS-001`, `SEC-INJ-001`, `SEC-INJ-002`, `SEC-XSS-001`,
   `SEC-AUTHZ-001`, `SEC-DESER-001`) cannot be disabled at any layer, and their severity
   stays at `blocker` below the org layer. Rule ids are compared case-insensitively.
5. **Provenance.** Every leaf key records the layer that set it (`explain`). Profile
   keys are recorded as `profile:<name>`, registry keys as `registry:<match>`.
6. **Effective config hash.** The first 16 hex characters of the SHA-256 of the
   canonical JSON of the effective config. Recorded in `stats.config_hash`, so every
   result can be tied to the exact configuration that produced it.
7. **Repository config source.** It is read from the target branch. Reading from the
   change request head needs both a request asking for it and the org setting
   `repo_config.allow_head_ref`. Skills follow the same rule (`skills.ref`, org-only).
8. **Hot reload.** The org file and registry directories are polled by mtime and size,
   and reloaded on SIGHUP. A failed reload keeps the last good configuration, increments
   `squad_config_reload_failures_total` and logs a warning. The failed signature is
   remembered, so a broken file is reported once rather than on every poll.
9. **Credentials are names.** Secret fields hold names that must match
   `secrets.allowed_patterns` (org-only). Values are read through the secret provider.
   Names containing path separators or `..` are refused before any filesystem access.

## Consequences

- A repository can tune its own review without touching the platform, and cannot
  widen what the platform allows. The rejection message says which key and why.
- Because layers are all-or-nothing, a repository author who makes one mistake loses
  every setting in that file. The warning names the failing key, and `squad config
  validate` and `squad config explain --repo-config` show the same result locally.
- Budgets are checked against `limits.*`, not against the inherited value, so a
  repository may raise its own budget up to the platform ceiling. Operators who want a
  lower per-project budget set it in the registry.
- Environment variables cannot express rule ids with hyphens reliably, because map keys
  are lowercased. Rule ids in environment overrides are matched case-insensitively for
  floor rules, and everything else belongs in the YAML file.
- The runtime must intersect `tool_allowlist` with the agent's own tools. Configuration
  can narrow the list but cannot name tools an agent does not have.
- Open point for review: `review.ignore_globs` and `security.accepted_risks` are
  repository-extensible. A repository can therefore hide files or accept advisories.
  Both are visible in the summary, but the architect may prefer org-only for them.
