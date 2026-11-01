---
title: Kubernetes manifest review (operational)
source: Kubernetes documentation (Deployments, probes, PodDisruptionBudget, topology spread, HorizontalPodAutoscaler, API deprecation guide); Kubernetes Pod Security Standards
version: Kubernetes 1.30 to 1.33 API set (verify the cluster version and deprecation notes for the target)
reviewed: 2026-10
unverified-edition: true
---

## Scope

Operational review of Kubernetes manifests (Deployment, StatefulSet, DaemonSet, Service, Ingress, HPA, PDB, ConfigMap, NetworkPolicy, Job, CronJob). Covers resource sizing, probes, rollout behaviour, availability during disruption, scheduling, and API version currency. Security context and RBAC depth are in `security/docker-k8s-hardening`. Helm and Kustomize rendering is in `helm-kustomize.md`.

## Rules

### OPS-K8S-001 — Resource requests and limits

- **Look for:** containers without `resources.requests`; memory limits lower than typical working set; CPU limits on latency-sensitive services that cause throttling; no limits at all in shared namespaces.
- **Why it matters:** missing requests prevent sensible scheduling; missing memory limits allow node pressure; very low limits produce OOMKilled restarts.
- **Good:** requests from measured usage; memory limit with headroom; CPU limit omitted or set with care.
- **Default severity:** medium; high where a missing limit affects shared nodes.

### OPS-K8S-002 — Liveness, readiness, and startup probes

- **Look for:** no readiness probe on a service behind a Service; liveness probe that checks dependencies (a downstream outage restarts healthy pods); probe timeouts shorter than real response times; no startup probe for slow-starting JVM or migration-heavy services (liveness fires too early).
- **Good:** readiness checks local readiness and critical dependencies needed to serve; liveness checks only the process; startup probe covers slow starts.
- **Default severity:** high for liveness that checks dependencies; medium otherwise.

### OPS-K8S-003 — Rollout strategy and surge

- **Look for:** `maxUnavailable` set to a value that drops capacity below need; `maxSurge: 0` with `maxUnavailable: 0` (cannot roll); missing `minReadySeconds` on services that fail shortly after start.
- **Good:** `maxSurge: 25%` and `maxUnavailable: 0` for user-facing services with readiness probes; `minReadySeconds` for a short stabilisation period.
- **Default severity:** medium.

### OPS-K8S-004 — PodDisruptionBudget

- **Look for:** replicated services with no PDB; PDB `minAvailable` equal to replica count (blocks node drains); PDB selecting nothing.
- **Good:** `policy/v1` PDB with `maxUnavailable: 1` or `minAvailable` below replica count.
- **Default severity:** medium.

### OPS-K8S-005 — Replica count and availability

- **Look for:** one replica for user-facing services without justification; replicas pinned in manifests while an HPA also controls them (conflict); no anti-affinity or topology spread for multi-replica services.
- **Good:** at least two replicas for critical services; HPA owns replica count; `topologySpreadConstraints` across zones or nodes.
- **Default severity:** medium to high for single-replica critical services.

### OPS-K8S-006 — Topology spread and affinity

- **Look for:** all replicas schedulable on one node; `podAntiAffinity` with `required` on a small cluster (pending pods); topology keys that do not exist on nodes.
- **Good:** `topologySpreadConstraints` with `whenUnsatisfiable: ScheduleAnyway` unless a hard requirement is documented.
- **Default severity:** medium.

### OPS-K8S-007 — Horizontal Pod Autoscaler

- **Look for:** HPA on CPU only for I/O-bound services; no `minReplicas`; `maxReplicas` unbounded; HPA `autoscaling/v2beta2` (removed in 1.26); scale-down too aggressive for connection-heavy services.
- **Good:** `autoscaling/v2` with CPU or custom metrics, sensible `behavior` settings for scale-down stabilisation.
- **Default severity:** low to medium.

### OPS-K8S-008 — Image references and pull policy

- **Look for:** `image: app:latest`; `imagePullPolicy: Always` combined with mutable tags in production; missing `imagePullSecrets` for private registries (leads to ImagePullBackOff).
- **Default severity:** medium to high.

### OPS-K8S-009 — ConfigMap and Secret usage

- **Look for:** configuration changes that do not roll pods (ConfigMap mounted as env, which does not update running pods); secrets in ConfigMaps; `envFrom` with broad sources that include unrelated keys.
- **Good:** config hash annotation to trigger rollouts, explicit `env` entries, and Secret references.
- **Default severity:** medium.

### OPS-K8S-010 — API version currency

- **Look for:** API versions removed in the target cluster version. Known removals: `policy/v1beta1` PodDisruptionBudget (removed in 1.25), `networking.k8s.io/v1beta1` Ingress (removed in 1.22), `autoscaling/v2beta2` HPA (removed in 1.26). Check the deprecation guide for any other version in the manifest.
- **Why it matters:** apply fails at deploy time or the object is not served.
- **Evidence:** the apiVersion line and the target cluster version. If the target is unknown, state it and check the current deprecation guide.
- **Default severity:** high when the target cluster does not serve the version.

### OPS-K8S-011 — Job and CronJob behaviour

- **Look for:** CronJob without `concurrencyPolicy` (Allow by default, can overlap); no `startingDeadlineSeconds`; no `activeDeadlineSeconds` or `backoffLimit` on Jobs; no `ttlSecondsAfterFinished`, so finished pods accumulate.
- **Default severity:** medium.

### OPS-K8S-012 — Services and ingress exposure

- **Look for:** `type: LoadBalancer` or `NodePort` for internal services; Ingress without TLS; annotations that disable TLS redirection; wildcard hosts.
- **Default severity:** medium to high.

### OPS-K8S-013 — Labels, selectors, and ownership

- **Look for:** Deployment selectors that change between versions (requires recreation); labels missing `app.kubernetes.io/*` standard labels used by dashboards and policies; duplicate selectors across workloads.
- **Default severity:** low to medium.

### OPS-K8S-014 — Termination and shutdown

- **Look for:** no `preStop` hook or sleep for services behind load balancers (connections dropped during endpoint update); `terminationGracePeriodSeconds` shorter than the application's drain time.
- **Default severity:** medium.

### OPS-K8S-015 — Storage claims

- **Look for:** StatefulSet `volumeClaimTemplates` changed in place (requires recreation); PVC access modes that do not match the scheduling model; no reclaim policy on data volumes.
- **Default severity:** medium to high for data loss risk.

## How to apply in review

1. Confirm the target cluster version and the API versions it serves.
2. For each workload, check: replicas, probes, resources, rollout, PDB, and spread, in that order.
3. Compare the manifest with the previous version when available; flag changes that break rollouts.
4. Cite the resource kind, name, and field path.
5. Suggest a concrete change and the failure it prevents. Do not request every field for every workload.
