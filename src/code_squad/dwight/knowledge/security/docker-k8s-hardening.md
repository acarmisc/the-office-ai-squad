---
title: Container and Kubernetes hardening (CIS-style checks)
source: CIS Docker Benchmark; CIS Kubernetes Benchmark (use the version the organisation adopts); Kubernetes Pod Security Standards (privileged, baseline, restricted); NSA/CISA Kubernetes Hardening Guidance
version: Kubernetes Pod Security Standards (current docs); CIS benchmark version to be stated by the project
reviewed: 2026-10
unverified-edition: true
---

## Scope

Security checks for Dockerfiles, container images, and Kubernetes manifests: user, privileges, capabilities, filesystem, network, secrets, image provenance, and resource limits as they affect security. Operational concerns (probes, rollouts) are covered by `darryl`. This file lists the security-relevant subset.

Use CIS-style checks as a checklist. Do not cite a CIS control number unless the project's benchmark version is known.

## Rules

### SEC-DOCKER-001 — Container runs as root

- **Look for:** no `USER` instruction in the final stage; `USER root`; Kubernetes `runAsNonRoot` missing or false; `runAsUser: 0`.
- **Good:** create a non-root user with a fixed numeric id and set `USER 10001:10001`; set `runAsNonRoot: true` and `runAsUser` in the pod security context.
- **Default severity:** high.
- **CWE:** CWE-250, CWE-269.

### SEC-DOCKER-002 — Privileged containers and host access

- **Look for:** `privileged: true`; `hostPID`, `hostIPC`, `hostNetwork`; `hostPath` volumes mounting sensitive host paths (`/`, `/var/run/docker.sock`, `/etc`); Docker socket mounted into workloads.
- **Why it matters:** host escape.
- **Default severity:** critical for docker.sock or privileged; high for other host access.

### SEC-DOCKER-003 — Capabilities

- **Look for:** `capabilities.add` with `SYS_ADMIN`, `NET_ADMIN`, `SYS_PTRACE`, `ALL`; missing `capabilities.drop: ["ALL"]`.
- **Good:** drop all capabilities and add only what is required.
- **Default severity:** high for `SYS_ADMIN` or `ALL`; medium otherwise.

### SEC-DOCKER-004 — Privilege escalation

- **Look for:** `allowPrivilegeEscalation` not set to `false`; setuid binaries in images that are not needed; `sudo` installed in production images.
- **Default severity:** medium.

### SEC-DOCKER-005 — Read-only root filesystem

- **Look for:** `readOnlyRootFilesystem` absent or false; writable paths not declared as volumes.
- **Good:** `readOnlyRootFilesystem: true` with `emptyDir` for required writable paths.
- **Default severity:** medium.

### SEC-DOCKER-006 — Image provenance and tags

- **Look for:** `latest` or other mutable tags; images from unknown registries; base images without a digest; `FROM` lines with a branch name.
- **Good:** pin by digest (`image@sha256:...`) and use a maintained minimal base image. See `supply-chain-ssdf-slsa.md`.
- **Default severity:** medium; high for untrusted registries.
- **CWE:** CWE-1104, CWE-494.

### SEC-DOCKER-007 — Secrets in image or manifest

- **Look for:** `ENV` with secret values in Dockerfiles; secrets in manifests as plain `env.value`; ConfigMaps used for credentials; `imagePullSecrets` committed with real values.
- **Good:** Kubernetes Secrets from an external store, mounted or referenced by `secretKeyRef`; build secrets via BuildKit mounts.
- **Default severity:** high.
- **Detail:** `secrets-logging.md`.

### SEC-DOCKER-008 — Build hygiene in Dockerfiles

- **Look for:** `ADD` from remote URLs without checksum; `curl | sh`; package installs without pinned versions where security depends on them; build tools left in the runtime image; no `.dockerignore` (risk of copying `.git`, `.env`, keys).
- **Good:** multi-stage builds; `.dockerignore` excluding secrets and VCS metadata; verify downloads with checksums.
- **Default severity:** medium; high for `curl | sh` or copying keys.
- **CWE:** CWE-494, CWE-829.

### SEC-K8S-001 — Pod Security Standard level

- **Look for:** namespaces without the Pod Security admission label, or with `privileged` for application workloads; manifests that require privileges the `restricted` standard forbids.
- **Good:** enforce `restricted` for application namespaces; exceptions documented per workload.
- **Default severity:** medium; high for privileged application namespaces.

### SEC-K8S-002 — Security context completeness

- **Look for:** pods without `securityContext` at pod or container level; missing `seccompProfile: RuntimeDefault` (or `Localhost`); `runAsNonRoot` absent; `allowPrivilegeEscalation` absent.
- **Default severity:** medium.

### SEC-K8S-003 — Service account and token mounting

- **Look for:** `automountServiceAccountToken` left true for workloads that do not call the API; default service account used for application pods; cluster-admin or wildcard RBAC bound to workloads.
- **Good:** dedicated service account per workload; `automountServiceAccountToken: false` when not needed; least-privilege Role and RoleBinding.
- **Default severity:** high for wildcard or cluster-admin bindings; medium otherwise.
- **CWE:** CWE-250, CWE-269.

### SEC-K8S-004 — RBAC wildcards

- **Look for:** `verbs: ["*"]`, `resources: ["*"]`, `apiGroups: ["*"]`; `secrets` read permissions for broad subjects; `escalate`, `bind`, or `impersonate` verbs granted.
- **Default severity:** high to critical.

### SEC-K8S-005 — Network policy

- **Look for:** namespaces with no NetworkPolicy and no default deny; workloads exposed through `NodePort` or `LoadBalancer` without need; ingress allowed from all namespaces.
- **Good:** default deny per namespace; explicit allow rules for required flows.
- **Default severity:** medium.

### SEC-K8S-006 — Exposed services and ports

- **Look for:** management ports (debug, JMX, actuator, metrics) exposed in the Service or Ingress; `hostPort` set; wildcard ingress host.
- **Default severity:** high for management ports reachable externally.

### SEC-K8S-007 — Resource limits as a security control

- **Look for:** no CPU or memory limits, allowing a single workload to exhaust a node; no `ephemeral-storage` limits where logs are written.
- **Default severity:** low to medium. Operational sizing is `darryl`'s area.

### SEC-K8S-008 — Admission and image policy

- **Look for:** no admission control to enforce signed images, no policy against privileged pods; images pulled without verification in production clusters.
- **Default severity:** low to medium; advisory unless the project states a policy.

### SEC-K8S-009 — Host namespaces and volumes in workloads

- **Look for:** `hostNetwork: true` for application pods; `hostPath` for data that should be in a volume claim; writable host mounts.
- **Default severity:** high.

## How to apply in review

1. For Dockerfiles, check the final stage: user, base image pin, secrets, copied files.
2. For manifests, check the security context, service account, RBAC, network exposure, and image pinning.
3. Cite the file, the resource kind and name, and the field path (for example `spec.template.spec.containers[0].securityContext`).
4. Do not demand every control for every workload. Ask whether the workload needs the privilege before flagging it.
5. Route pipeline and rollout findings to `darryl`.
