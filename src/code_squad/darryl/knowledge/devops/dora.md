---
title: DORA metrics and how changes affect them
source: DORA State of DevOps research (dora.dev); "Accelerate" (Forsgren, Humble, Kim, 2018); DORA capabilities guidance
version: DORA four key metrics (deployment frequency, lead time for changes, change failure rate, failed deployment recovery time, also described as time to restore); reliability added as a fifth dimension in recent research
reviewed: 2026-10
---

## Scope

How to judge whether a change is likely to improve or degrade delivery performance, using DORA metrics as the reference. Applies to pipeline, release, and process changes. This is a review aid. A single merge request cannot prove a metric change; the rules state what to expect and what evidence to cite.

## Rules

### OPS-DORA-001 — Deployment frequency

- **Look for:** changes that add manual approval steps, batch releases, or freeze periods without a reason; pipeline changes that make deploys slower or more fragile.
- **Why it matters:** smaller, more frequent deployments generally carry less risk per change.
- **Evidence:** the deploy step added or removed, and its frequency constraints.
- **Default severity:** low (advisory) unless the change blocks deploys.

### OPS-DORA-002 — Lead time for changes

- **Look for:** pipeline stages that add long waits (serial test suites, unbounded manual gates, slow image builds without caching); queues on shared runners; approvals required for low-risk changes.
- **Good:** parallel jobs, caching, path-based rules, and risk-based approval.
- **Evidence:** job durations from the pipeline or the added stages.
- **Default severity:** low to medium when the change clearly lengthens the path.

### OPS-DORA-003 — Change failure rate

- **Look for:** changes that remove tests, relax gates (`allow_failure`, `continue-on-error`), skip migrations checks, or disable canaries; changes that increase blast radius (shared module changes, global configuration).
- **Why it matters:** the share of deployments that cause incidents or require remediation.
- **Evidence:** the removed or relaxed control, and the systems it protected.
- **Default severity:** high when a safety gate is removed from a production path; medium otherwise.

### OPS-DORA-004 — Time to restore service

- **Look for:** changes that remove or complicate rollback (no previous version artefact kept, rollback job removed, migrations that cannot be reversed); observability removed from the changed path; runbooks invalidated by the change.
- **Good:** keep the previous artefact deployable; keep rollback one command; keep dashboards and alerts current.
- **Default severity:** high when rollback is removed; medium when observability is reduced.

### OPS-DORA-005 — Reliability

- **Look for:** changes that alter capacity, timeouts, retries, or autoscaling without a load or failure test; retries without backoff that multiply load during incidents; health checks that cause restarts under load.
- **Default severity:** medium.

### OPS-DORA-006 — Do not game the metric

- **Look for:** changes that split one deployment into many trivial ones to raise frequency, or that re-label failed deployments as successful, or that exclude incidents from the measurement.
- **Why it matters:** the metric stops reflecting delivery health.
- **Default severity:** medium when evidence of gaming is visible.

### OPS-DORA-007 — Stating the expected effect

- **Look for:** pipeline and release changes presented with no statement of expected effect on lead time, frequency, failure rate, or restore time.
- **Good:** the MR states which metric is expected to move, in which direction, and how it will be checked after release.
- **Default severity:** low (process).

## How to apply in review

1. For each pipeline or release change, name the DORA metric it affects.
2. Check whether the change removes a safety control or a recovery path. Those findings outrank speed findings.
3. Cite the change and the metric, and state the direction and the evidence available.
4. Do not claim a metric improvement without measurement. Say "expected to" when there is no data.
5. Keep DORA findings advisory unless the change removes a control.
