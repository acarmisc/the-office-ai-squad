---
title: Helm charts and Kustomize overlays review
source: Helm documentation (chart best practices, values, hooks, upgrade and rollback flags); Kustomize documentation (overlays, generators, patches); Helm chart best practices guide
version: Helm 3.x; Kustomize 5.x (verify versions pinned in CI)
reviewed: 2026-10
unverified-edition: true
---

## Scope

Review of Helm charts (`Chart.yaml`, `values*.yaml`, `templates/`, hooks, tests) and Kustomize bases and overlays (`kustomization.yaml`, patches, generators). Covers rendered output correctness, values hygiene, environment overlays, upgrade behaviour, and rollback. The rendered manifests are reviewed with `kubernetes-manifests.md`.

## Rules

### OPS-HELM-001 — Render and diff before merge

- **Look for:** chart or overlay changes with no evidence of rendered output (no `helm template` or `kustomize build` in CI, no diff in the MR).
- **Why it matters:** template logic errors appear only in rendered YAML.
- **Good:** CI renders each environment and posts a diff, using `helm template` with the environment values, `helm lint`, and `kustomize build` with the overlay path.
- **Default severity:** medium.

### OPS-HELM-002 — Values schema and defaults

- **Look for:** new required values with no default; defaults that are unsafe for production (`debug: true`, `replicas: 1`, empty `image.tag`); values keys renamed without a compatibility path; no `values.schema.json` for charts consumed by others.
- **Good:** safe defaults, `required` for values that have no sensible default, and a schema for shared charts.
- **Default severity:** medium.

### OPS-HELM-003 — Template correctness

- **Look for:** `toYaml` without `nindent` leading to invalid indentation; `.Values.x` used without `default` or `required` where absence breaks rendering; `quote` missing around values that must be strings (numbers that become floats); `include` of undefined helpers.
- **Default severity:** medium (rendering failure), high when a value silently changes type.

### OPS-HELM-004 — Secrets in values

- **Look for:** passwords and tokens in `values.yaml` or environment overlays; secrets rendered into ConfigMaps; `helm secrets` or SOPS files without a clear decryption path in CI.
- **Good:** reference existing Secrets or an external secret operator; keep environment values free of secret material.
- **Default severity:** high. Report location only.

### OPS-HELM-005 — Hooks and their ordering

- **Look for:** hooks that run migrations without a timeout or deletion policy (`hook-delete-policy`); pre-upgrade hooks that cannot be rolled back; hook weights that order migrations after the rollout that needs them.
- **Why it matters:** failed migrations or stuck hook jobs block the release.
- **Good:** `helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded`, explicit weights, and a documented rollback for schema changes (see `release-safety.md`).
- **Default severity:** high for irreversible migrations in hooks; medium otherwise.

### OPS-HELM-006 — Upgrade and rollback flags

- **Look for:** `helm upgrade` in CI without `--atomic` or `--wait` and `--timeout`; no `--history-max`, so release history grows; rollback path not defined.
- **Good:** `helm upgrade --install --atomic --wait --timeout 10m --history-max 10`.
- **Default severity:** medium; high for production pipelines without atomic upgrades.

### OPS-HELM-007 — Chart version and dependencies

- **Look for:** chart `version` not bumped for template changes; dependencies with floating version ranges; `Chart.lock` missing when dependencies exist; `dependencies` pulled from unverified repositories.
- **Good:** `helm dependency build` with a committed `Chart.lock`; pinned dependency versions.
- **Default severity:** medium.

### OPS-HELM-008 — Resource names and release-name assumptions

- **Look for:** resource names hard-coded instead of using the release name, causing collisions when two releases share a namespace; names exceeding 63 characters; cluster-scoped resources created by a namespaced chart.
- **Default severity:** medium.

### OPS-HELM-009 — Kustomize base and overlay structure

- **Look for:** overlays that duplicate base files instead of patching; patches that target resources by name only, where kind and group are also needed; `namePrefix` or `nameSuffix` changing selectors; generators (`configMapGenerator`, `secretGenerator`) without `disableNameSuffixHash` decisions made deliberately.
- **Why it matters:** hash suffixes change names on every content change, which triggers rollouts and breaks external references.
- **Default severity:** medium.

### OPS-HELM-010 — Kustomize patch safety

- **Look for:** strategic merge patches that unintentionally remove fields (arrays replaced wholesale); JSON 6902 patches on indexes that shift when the base changes; patches that add `hostNetwork` or security relaxations in production overlays.
- **Good:** target by kind, name, and group; prefer strategic merge with explicit list keys; review `kustomize build` diff.
- **Default severity:** medium to high.

### OPS-HELM-011 — Environment parity

- **Look for:** production overlay that differs from staging in ways not documented (replicas, resources, feature flags); environment-specific logic in base templates; defaults that only work in one environment.
- **Default severity:** low to medium.

### OPS-HELM-012 — Tests and validation

- **Look for:** charts with no `helm test` or no schema validation in CI; rendered output not validated against the cluster's API versions (use a schema validator or a dry-run against the target API).
- **Default severity:** low to medium.

### OPS-HELM-013 — Chart and image separation

- **Look for:** image tags hard-coded in templates while chart version is unchanged, so a new image does not change the chart; `appVersion` out of step with the default image tag.
- **Default severity:** low.

## How to apply in review

1. Confirm the render command and environment used by CI. Ask for the rendered diff when it is missing.
2. Check values defaults for production safety, then check templates for type and indentation errors.
3. Check hooks and the upgrade command for atomicity and rollback.
4. For Kustomize, check patch targets and generators.
5. Cite the chart or overlay path and the template or patch line. Review the rendered resources with `kubernetes-manifests.md`.
