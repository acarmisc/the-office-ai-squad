---
title: GitHub Actions workflow review
source: GitHub Actions documentation (workflow syntax, permissions, events, OpenID Connect, security hardening for GitHub Actions); GitHub Changelog on pull_request_target
version: GitHub Actions current syntax (verify runner images in use)
reviewed: 2026-10
unverified-edition: true
---

## Scope

Review of `.github/workflows/*.yml`, reusable workflows, composite actions, and third-party actions referenced by workflows. Covers correctness, token permissions, trigger safety, action pinning, OIDC, and caching. Supply-chain depth is in `security/supply-chain-ssdf-slsa`; this file gives the workflow-level checks.

## Rules

### OPS-GHA-001 — Explicit least-privilege token permissions

- **Look for:** no top-level `permissions:` block; `permissions: write-all`; jobs requesting `contents: write`, `pull-requests: write`, or `id-token: write` without need.
- **Why it matters:** the default `GITHUB_TOKEN` permissions depend on repository settings and can be broader than required.
- **Good:** `permissions: contents: read` at the top level, and per-job grants for the few write scopes needed.
- **Default severity:** high for write-all; medium for missing top-level block.

### OPS-GHA-002 — Actions pinned by full commit SHA

- **Look for:** `uses: owner/action@v4` or `@main` for third-party actions; `uses:` of local actions without a checksum review; Docker actions pinned by tag.
- **Why it matters:** a tag can be moved to malicious code; a branch changes on every run.
- **Good:** `uses: owner/action@<40-char-sha> # v4.2.1` with the version in a comment, and an update process (for example automated update pull requests).
- **Default severity:** high for third-party actions with secrets or write permissions; medium otherwise.

### OPS-GHA-003 — pull_request_target and untrusted code

- **Look for:** `on: pull_request_target` combined with `actions/checkout` of the pull request head, or with running scripts from the PR; secrets available to forks through this trigger.
- **Why it matters:** `pull_request_target` runs in the base repository context with secrets and a write-capable token. Checking out and executing untrusted head code grants the fork access to those secrets.
- **Good:** use `pull_request` for untrusted code; use `pull_request_target` only for metadata operations (labelling, comments) that do not run PR code.
- **Default severity:** critical when PR code runs with secrets; high otherwise.

### OPS-GHA-004 — Script injection through context expressions

- **Look for:** `${{ github.event.issue.title }}`, `${{ github.event.pull_request.title }}`, `${{ github.head_ref }}`, `${{ github.event.comment.body }}`, or other user-controlled fields interpolated directly into `run:` scripts.
- **Why it matters:** the expression is substituted before the shell runs, so crafted titles or branch names execute commands.
- **Good:** pass the value through `env:` and reference the shell variable (`"$TITLE"`), and quote it.
- **Bad:** `run: echo "${{ github.event.pull_request.title }}"`
- **Good:** `env: TITLE: ${{ github.event.pull_request.title }}` then `run: echo "$TITLE"`
- **Default severity:** high; critical where the job has secrets or write tokens.

### OPS-GHA-005 — Checkout credentials

- **Look for:** `actions/checkout` with default `persist-credentials: true` followed by steps that run untrusted code; checkout of a ref controlled by the event, then push to that ref.
- **Good:** `persist-credentials: false` unless a later step pushes; pin the ref to the event's commit SHA.
- **Default severity:** medium to high.

### OPS-GHA-006 — OIDC for cloud access

- **Look for:** long-lived cloud keys stored as repository secrets when OIDC federation is available; `id-token: write` granted at the workflow level instead of the job that needs it; trust conditions that accept any branch or any repository.
- **Good:** `id-token: write` on the deploy job only; cloud trust conditions restricted to the repository, the environment or branch, and the workflow file.
- **Default severity:** high for wildcard trust; medium otherwise.

### OPS-GHA-007 — Environments and deployment protection

- **Look for:** deploy jobs without `environment:`; production environment without required reviewers or branch restrictions (report what the YAML implies; settings must be checked separately); secrets scoped at repository level instead of environment level.
- **Default severity:** high for production deploys without environment scoping.

### OPS-GHA-008 — Reusable workflows and composite actions

- **Look for:** `workflow_call` inputs used in `run:` without escaping; secrets passed with `secrets: inherit` to a workflow from another repository; composite actions that run shell with unquoted inputs.
- **Default severity:** medium to high.

### OPS-GHA-009 — Triggers and concurrency

- **Look for:** `on: push` with no branch filter on workflows that deploy; `on: workflow_run` chains that run privileged code on artefacts from untrusted runs; no `concurrency:` on deploy workflows.
- **Good:** `concurrency: group: deploy-${{ github.ref }}`, `cancel-in-progress: false` for deploys.
- **Default severity:** medium to high for deploy concurrency.

### OPS-GHA-010 — Cache use and key design

- **Look for:** cache keys that do not include the lockfile hash; caches restored in privileged workflows from untrusted pull request caches (cache poisoning).
- **Good:** `key: ${{ runner.os }}-npm-${{ hashFiles('package-lock.json') }}`; avoid writing caches from untrusted contexts that privileged workflows restore.
- **Default severity:** medium.

### OPS-GHA-011 — Runner selection

- **Look for:** `runs-on: self-hosted` for public repositories (anyone who can open a pull request can run code on the runner); shared self-hosted runners without ephemeral mode.
- **Default severity:** high for public repositories with self-hosted runners.

### OPS-GHA-012 — Timeouts, matrix, and cost

- **Look for:** no `timeout-minutes` on long jobs; matrices that multiply runs without need; `continue-on-error: true` on required checks.
- **Default severity:** low to medium.

### OPS-GHA-013 — Secrets in logs and artefacts

- **Look for:** `echo` of secrets; `set -x` before secret use; `actions/upload-artifact` paths that include `.env`, credential files, or kubeconfig.
- **Note:** GitHub masks registered secrets in logs, but transformed or split values can leak.
- **Default severity:** high. Report location only.

### OPS-GHA-014 — Deprecated actions and runner images

- **Look for:** actions on deprecated Node runtimes or unmaintained versions; `ubuntu-latest` used for reproducibility-sensitive builds without a note; `set-output` or `save-state` commands (deprecated in favour of environment files).
- **Default severity:** low to medium.

## How to apply in review

1. Check the `on:` triggers first. A dangerous trigger overrides everything else.
2. Check `permissions:` at workflow and job level.
3. Search `run:` blocks for `${{ ... }}` interpolations of event data.
4. Check every `uses:` reference for pinning and source.
5. Check OIDC trust and environment protection for each deploy job.
6. Cite the workflow path, job name, and line. Route action supply-chain depth to `dwight`.
