---
title: Terraform and OpenTofu review
source: HashiCorp Terraform documentation (language, state, backends, lifecycle, plan); OpenTofu documentation (compatible language features); Terraform style and conventions guide
version: Terraform 1.x (current minor at review date; verify the version pinned in required_version); OpenTofu 1.x where used
reviewed: 2026-10
unverified-edition: true
---

## Scope

Review of Terraform or OpenTofu configuration: providers, modules, state and backends, resource lifecycle, plan output, and change blast radius. Applies to `*.tf`, `*.tfvars`, `.terraform.lock.hcl`, and related CI steps. Security of cloud resources (public exposure, encryption) is covered by `security/docker-k8s-hardening` and the cloud-specific guidance in the project; this file focuses on operational safety.

## Rules

### OPS-TF-001 — Plan is reviewed before apply

- **Look for:** CI that applies without a saved plan artefact; `apply -auto-approve` on non-ephemeral environments; no plan output in the merge request.
- **Good:** `terraform plan -out=tfplan` in MR pipelines, the plan posted for review, and `apply tfplan` from the approved artefact only.
- **Default severity:** high for production applies without a reviewed plan.

### OPS-TF-002 — Destructive changes are visible

- **Look for:** changes that replace resources (`-/+` in plan) for stateful or identity-bearing resources (databases, DNS zones, load balancers, buckets, KMS keys); renames of resources without `moved` blocks (which causes destroy and create).
- **Good:** `moved` blocks for renames; `lifecycle { prevent_destroy = true }` on stateful resources; `create_before_destroy` where replacement must not drop traffic.
- **Default severity:** critical for unplanned destruction of stateful resources; high otherwise.

### OPS-TF-003 — Remote state and locking

- **Look for:** local state files committed or used in CI; backends without locking (for example S3 without DynamoDB lock table or native locking where the version supports it); state shared between environments; state files containing secrets stored without encryption.
- **Good:** remote backend with encryption and locking; one state per environment and stack; restricted access to state.
- **Default severity:** high.

### OPS-TF-004 — Provider and module version pins

- **Look for:** `required_providers` without version constraints; `version = ">= 0"`; modules sourced from branches or `latest`; `.terraform.lock.hcl` missing or not updated with provider changes.
- **Good:** pessimistic constraints (`~> 5.0`), exact module versions or tags, committed lock file.
- **Default severity:** medium; high for unpinned provider major versions in production.

### OPS-TF-005 — Blast radius of the root module

- **Look for:** one root module managing networking, databases, clusters, and application resources together; long plan times and wide dependency graphs; `-target` used regularly in pipelines.
- **Why it matters:** a failed or wrong apply affects unrelated systems. `-target` bypasses the dependency graph and hides drift.
- **Default severity:** medium.

### OPS-TF-006 — Drift and manual changes

- **Look for:** resources changed outside Terraform (described in comments or tickets); `ignore_changes` on attributes that matter for security or capacity; no scheduled plan to detect drift.
- **Good:** scheduled drift detection with a plan-only job; `ignore_changes` narrowly scoped and documented.
- **Default severity:** medium.

### OPS-TF-007 — Variables, outputs, and sensitive values

- **Look for:** secrets in `.tfvars` committed to the repository; sensitive values written to outputs without `sensitive = true`; secrets passed as plain variables visible in plan output; defaults for credentials.
- **Good:** secrets from a secret store or environment, marked `sensitive`; no defaults for credentials.
- **Default severity:** high. Report location only.

### OPS-TF-008 — Count, for_each, and index instability

- **Look for:** `count` over a list that can be reordered or filtered, causing resources to be destroyed and recreated; `for_each` keyed by values that change.
- **Good:** `for_each` keyed by stable identifiers.
- **Default severity:** high when the resource is stateful.

### OPS-TF-009 — Module interface quality

- **Look for:** modules that expose too many variables without defaults; outputs that leak internal resource attributes; module inputs typed as `any`; missing `validation` blocks for constrained inputs.
- **Default severity:** low to medium.

### OPS-TF-010 — Terraform version constraints

- **Look for:** missing `required_version` in the root module; CI pinned to a different version from local tooling; use of features that require a newer minor version than the constraint allows.
- **Default severity:** medium.

### OPS-TF-011 — Data sources and external calls

- **Look for:** `external` data sources or `local-exec` provisioners running scripts with credentials; data sources that fail when a resource does not yet exist (ordering); `remote-state` data sources reading state from other stacks without a contract.
- **Default severity:** medium to high for `local-exec` with secrets.

### OPS-TF-012 — Deletion protection and backups

- **Look for:** managed databases and storage without deletion protection or backup configuration in the resource definition; retention settings that shorten backup windows; no `prevent_destroy` on key stores.
- **Default severity:** medium to high.

### OPS-TF-013 — Formatting and validation in CI

- **Look for:** CI without `terraform fmt -check`, `terraform validate`, and a linter (for example TFLint, where the project uses it); no policy check on plans where the project uses one.
- **Default severity:** low.

## How to apply in review

1. Read the plan output first. Identify every create, update, replace, and destroy.
2. Check each destroy or replace against stateful resource rules (OPS-TF-002).
3. Check state backend and locking before anything else in a new stack.
4. Check provider and module pins in the lock file.
5. Cite the resource address (for example `module.db.aws_db_instance.main`) and the plan action.
