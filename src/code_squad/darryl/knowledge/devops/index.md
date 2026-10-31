---
title: DevOps knowledge pack index
source: Project-authored index of the devops/ knowledge pack
version: GitLab CI 17.x; GitHub Actions current syntax; Kubernetes 1.30 to 1.33 API set; Terraform 1.x; Helm 3.x; Kustomize 5.x; DORA metrics (current guidance)
reviewed: 2026-10
---

## Scope

Index of the DevOps pack used by `darryl` (DevOps reviewer and troubleshooter). Topic id is the file path without `.md`, for example `devops/k8s-failure-patterns`. Load a topic with `read_knowledge(topic)` only for the files in the diff or the symptom under investigation.

## Rules

Review topics (mode `review`):

- `devops/gitlab-ci`: rules, workflow, needs, caching, artefacts, deploy protection, includes, ID tokens, resource groups.
- `devops/github-actions`: token permissions, SHA pinning, `pull_request_target`, script injection, checkout credentials, OIDC, environments.
- `devops/dockerfile`: multi-stage builds, base image pinning, non-root user, build secrets, `ADD` and remote content, `.dockerignore`.
- `devops/kubernetes-manifests`: resources, probes, rollout, PodDisruptionBudget, spread, HPA, API version currency, jobs.
- `devops/helm-kustomize`: rendering, values safety, hooks, atomic upgrades, Kustomize patches and generators.
- `devops/terraform`: plan review, destructive changes, remote state and locking, pins, drift, sensitive values.
- `devops/release-safety`: rollback paths, expand and contract migrations, feature flags, gradual rollout, config as release.
- `devops/dora`: how changes affect the four DORA metrics and reliability.

Troubleshooting topics (mode `troubleshoot`):

- `devops/troubleshooting-method`: symptom, blast radius, ranked hypotheses, read-only evidence, confirmation, conclusion or explicit unknown, remediation and rollback, unchecked items.
- `devops/k8s-failure-patterns`: CrashLoopBackOff, OOMKilled, image pull failures, failed rollouts, probe failures, pending pods, DNS, endpoints, certificate expiry, connection errors, evictions, RBAC denials.

Rule id prefixes: `OPS-CI`, `OPS-GHA`, `OPS-DOCK`, `OPS-K8S`, `OPS-HELM`, `OPS-TF`, `OPS-REL`, `OPS-DORA`, `OPS-TSHOOT`, `OPS-FAIL`.

## How to apply in review

1. Identify the files in scope: pipeline, container, manifest, chart, Terraform, or workflow.
2. Load the matching review topics. Load `devops/release-safety` for any change that reaches production.
3. For troubleshooting, load `devops/troubleshooting-method` first, then the failure family.
4. Security issues found in these files are reported with the `SEC-*` rule from `security/` and routed to `dwight`.
5. Remediation is advice only. Do not propose cluster mutations as completed actions.
