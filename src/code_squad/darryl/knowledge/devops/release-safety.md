---
title: Release safety: rollout, rollback, migrations and feature flags
source: Google SRE Book and SRE Workbook (release engineering, canarying releases); Martin Fowler and Pete Hodgson, Feature Toggles; expand and contract schema change pattern; Kubernetes rollout documentation
version: Practice guidance; tool-specific details follow the project's deployment platform
reviewed: 2026-10
---

## Scope

Whether a change can be released and reversed safely. Covers rollout strategy, rollback paths, database and schema migrations, feature flags, configuration changes, and change windows. Applies to any change that alters runtime behaviour, data, or infrastructure. Pipeline mechanics are in the CI files; this file is about the release decision.

## Rules

### OPS-REL-001 — Every release has a rollback path

- **Look for:** changes with no stated rollback (redeploy previous version, revert migration, disable flag); schema changes that cannot be reversed by deploying the previous code; data migrations with no backup or reversal plan.
- **Why it matters:** rollback is the fastest mitigation during an incident.
- **Good:** the MR states how to roll back, and the rollback has been exercised in a non-production environment for risky changes.
- **Default severity:** high for irreversible data changes without a plan; medium otherwise.

### OPS-REL-002 — Expand and contract for schema changes

- **Look for:** a single release that renames or drops a column used by the previous version still running; adding a non-null column without a default; changing a column type in place; removing a field from an API the old version reads.
- **Why it matters:** during a rolling deploy, old and new versions run together. A breaking schema change breaks the old version.
- **Good:** expand (add nullable column, write both), migrate data, switch reads, then contract (remove old column) in a later release.
- **Default severity:** critical for destructive changes to tables in use; high for non-compatible additions.

### OPS-REL-003 — Migrations are separated from application startup

- **Look for:** migrations run automatically at application startup on every replica; long-running migrations that block startup and trigger probe failures; migrations with no lock timeout.
- **Good:** a separate migration job run once before the rollout, with a lock timeout and a documented expected duration.
- **Default severity:** high.

### OPS-REL-004 — Long-running and locking migrations

- **Look for:** `ALTER TABLE` on large tables without online-capable approach; index creation without concurrent option where supported; backfills in a single transaction; no batching for large updates.
- **Good:** batched backfills, concurrent index creation, and a short lock timeout that fails fast.
- **Default severity:** high on large production tables.

### OPS-REL-005 — Feature flags for risky behaviour

- **Look for:** large behaviour changes shipped without a flag; flags without an owner, default, or removal plan; flags that change data writes without a read path for both states.
- **Good:** flag defaults off in production, a documented owner, a removal ticket, and tests for both states.
- **Default severity:** medium.

### OPS-REL-006 — Gradual rollout

- **Look for:** all-at-once rollout for user-facing changes in services with many replicas; no canary or percentage rollout where the platform supports it; no health gate between stages.
- **Good:** canary or staged rollout with metrics gates (error rate, latency, saturation) and automatic or manual rollback on breach.
- **Default severity:** medium; high for payment or identity services.

### OPS-REL-007 — Config changes are releases

- **Look for:** configuration changes (environment variables, feature settings, timeouts, connection pool sizes) applied without review or without a rollback; config changes that require a restart not planned.
- **Why it matters:** many incidents come from configuration.
- **Good:** config under version control with the same review as code; each change has a rollback value.
- **Default severity:** medium.

### OPS-REL-008 — Backward and forward compatibility

- **Look for:** API or message format changes that break the previous consumer during rollout; events renamed or removed; version negotiation missing.
- **Good:** additive changes first; consumers upgraded before producers for breaking changes; versioned contracts.
- **Default severity:** high for externally consumed contracts.

### OPS-REL-009 — Timing and change windows

- **Look for:** releases of high-risk changes on Fridays or before holidays without a stated reason; changes during an active incident; changes overlapping other major releases on the same dependency.
- **Good:** follow the project's change calendar; record the reason for out-of-window releases.
- **Default severity:** low to medium.

### OPS-REL-010 — Observability for the release

- **Look for:** no new metrics, logs, or traces for new behaviour; no dashboard or alert for the changed path; no way to tell which version served a request.
- **Good:** version label on metrics and logs; alerts for the new error paths; release marker on dashboards.
- **Default severity:** low to medium.

### OPS-REL-011 — Backups before destructive operations

- **Look for:** data deletion, bulk updates, or table drops in migrations without a backup or snapshot step; backups not verified for restoration.
- **Default severity:** high.

### OPS-REL-012 — Dependencies that change runtime behaviour

- **Look for:** major framework, runtime, or base image upgrades bundled with feature changes; default behaviour changes in dependencies (for example, timezone or serialisation defaults) without tests.
- **Default severity:** medium.

## How to apply in review

1. For each change, ask: what does rollback look like, and does the old version still work with the new data and config?
2. For each migration, classify it: additive, backfill, destructive. Apply OPS-REL-002 to destructive ones.
3. Check the rollout strategy and its health gates.
4. Cite the migration file, the release configuration, or the flag definition.
5. State the rollback as a concrete step, not a general intention.
