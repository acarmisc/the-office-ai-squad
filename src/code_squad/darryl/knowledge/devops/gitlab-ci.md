---
title: GitLab CI/CD pipeline review
source: GitLab CI/CD documentation (YAML reference: rules, needs, cache, artifacts, workflow, id_tokens, resource_group, interruptible); GitLab security guidance for CI/CD
version: GitLab 17.x and later (verify the instance version where known)
reviewed: 2026-10
unverified-edition: true
---

## Scope

Review of `.gitlab-ci.yml`, included files (`include:`), templates, and job definitions in merge request pipelines. Covers correctness, speed, reproducibility, secrets handling, and release safety. Security depth is delegated to `dwight` (`security/supply-chain-ssdf-slsa`); cite its rule ids when the issue is primarily security.

## Rules

### OPS-CI-001 — Rules replace only and except

- **Look for:** `only:` or `except:` in new jobs; `rules:` combined with `only:`; jobs with no `rules` in a project that uses `rules` elsewhere, so they run on every ref.
- **Why it matters:** `only` and `except` are legacy and interact unpredictably with merge request pipelines. Missing rules run jobs on unintended refs.
- **Good:** `rules: - if: $CI_PIPELINE_SOURCE == "merge_request_event"` and explicit `when:` values.
- **Default severity:** medium.

### OPS-CI-002 — Workflow rules prevent duplicate pipelines

- **Look for:** pipelines that run twice for a push to a branch with an open merge request; no `workflow:rules` block in projects that use both branch and MR triggers.
- **Good:** `workflow:rules` that select merge request pipelines when present and branch pipelines otherwise.
- **Default severity:** low to medium (cost and confusion).

### OPS-CI-003 — Needs and stage ordering

- **Look for:** jobs that could run in parallel but wait for a whole stage (`stages` without `needs`); `needs` referencing jobs that do not exist or are skipped by rules, which fails the pipeline.
- **Why it matters:** slow pipelines and failures on skipped dependencies. `needs` creates a DAG.
- **Good:** `needs:` for the true dependencies; `needs: [{job: x, optional: true}]` where a job may be skipped.
- **Default severity:** low (speed) to high (broken dependency).

### OPS-CI-004 — Caching is keyed and scoped

- **Look for:** `cache:` keyed on a constant string, so changes in lockfiles never invalidate it; caches shared between protected and unprotected branches; caches used for build outputs that should be artefacts; `cache:policy` missing on jobs that only read.
- **Good:** `cache:key:files: [package-lock.json]`, `policy: pull` for read-only jobs, `artifacts` for outputs consumed by later jobs.
- **Default severity:** medium.

### OPS-CI-005 — Artefacts have expiry and scope

- **Look for:** artefacts without `expire_in` (retained by default for a long period); large artefacts uploaded for every job; `artifacts:paths` including secrets or `.env`; `artifacts:reports` missing where a test or coverage report is consumed.
- **Default severity:** low to medium; high when secrets are in artefact paths.

### OPS-CI-006 — Interruptible jobs

- **Look for:** long test or build jobs without `interruptible: true` on a project that cancels redundant pipelines; deploy jobs marked interruptible.
- **Why it matters:** redundant work continues after a newer commit. Deploy jobs must never be interruptible.
- **Default severity:** low (cost); high for deploy jobs marked interruptible.

### OPS-CI-007 — Image pinning

- **Look for:** `image: node:latest` or other mutable tags in jobs; images from unknown registries; `services:` without versions.
- **Good:** pin to a version tag, and to a digest where the project requires reproducibility.
- **Default severity:** medium.

### OPS-CI-008 — Variables and masking

- **Look for:** secrets defined in `variables:` in the YAML file; secret values echoed in `script:` (`echo $TOKEN`, `set -x` with secret use); variables not masked or protected in project settings (report what the YAML implies and ask for settings check).
- **Why it matters:** secrets in YAML are visible to everyone with repository read access.
- **Default severity:** high. Report location only.
- **Cross-reference:** `security/secrets-logging` SEC-SECRETS-003.

### OPS-CI-009 — Protected and environment-scoped deploys

- **Look for:** deploy jobs that run on any branch; production deploys without `environment:` and `when: manual` or protected branch rules; deploy jobs using variables not scoped to the protected environment.
- **Good:** `environment: name: production`, `rules` limited to protected refs, `when: manual` for production where the process requires it.
- **Default severity:** high for production deploys reachable from unreviewed refs.

### OPS-CI-010 — Include and template sources

- **Look for:** `include: remote:` or `include: project:` without a `ref` pin; `include` of templates from branches (`ref: main`); templates that execute arbitrary scripts from another project without ownership review.
- **Good:** pin `ref` to a tag or commit; review template changes as code.
- **Default severity:** medium to high (depends on what the template runs).
- **Cross-reference:** `security/supply-chain-ssdf-slsa` SEC-SUPPLY-004.

### OPS-CI-011 — ID tokens and cloud federation

- **Look for:** long-lived cloud credentials in variables where `id_tokens` with OIDC federation is available; `id_tokens` `aud` values that are overly broad or shared by many projects.
- **Good:** short-lived credentials from an OIDC trust with a narrow audience and subject condition.
- **Default severity:** medium.

### OPS-CI-012 — Resource groups for deploys

- **Look for:** two deploy jobs for the same environment that can run concurrently; no `resource_group` on production deploy jobs.
- **Why it matters:** concurrent deploys race and leave mixed state.
- **Default severity:** medium.

### OPS-CI-013 — Failure visibility and retries

- **Look for:** `allow_failure: true` on jobs that gate releases or security scans; `retry:` used to hide flaky tests without a ticket; `retry: 2` with no `when` restriction on deploy jobs (repeat deploys).
- **Default severity:** medium.

### OPS-CI-014 — Timeouts and runner tags

- **Look for:** no `timeout` on jobs that call the network; jobs without runner tags on a project with mixed runners (wrong runner class, for example a privileged shared runner used for untrusted code).
- **Default severity:** low to medium.

### OPS-CI-015 — Docker-in-Docker and privileged runners

- **Look for:** `privileged: true` runners or `services: docker:dind` used on shared runners for untrusted merge request code.
- **Why it matters:** a merge request can escape to the host or read other jobs' data.
- **Default severity:** high.

## How to apply in review

1. Read `workflow:` and the rules that select pipelines first.
2. For each deploy job, check the trigger, the environment, the protection, and the concurrency group.
3. Check each job's image, cache key, and artefact paths.
4. Check each include and template for pinning.
5. Cite the job name and line. Propose the smallest YAML change, and state what it changes in behaviour.
