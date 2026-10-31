---
title: Kubernetes failure patterns and first checks
source: Kubernetes documentation (Debug Pods, Debug Services, Pod lifecycle, Pod Quality of Service, Container probes, DNS for Services and Pods, certificate management); kubectl reference
version: Kubernetes 1.30 to 1.33 behaviour (verify against cluster version)
reviewed: 2026-10
unverified-edition: true
---

## Scope

Common Kubernetes failure families, with the signals that identify each one (in `kubectl get`, `describe`, `events`, `logs`, and `top`) and the next read-only checks. Use this file in `troubleshoot` mode after the symptom is restated (`troubleshooting-method.md` OPS-TSHOOT-001). Commands shown are read-only.

Each pattern gives: signals, likely causes, and next checks. Causes are hypotheses until confirmed by evidence.

## Rules

### OPS-FAIL-001 — CrashLoopBackOff from bad environment or configuration

- **Signals:** pod status `CrashLoopBackOff`, restart count increasing; last state exit code 1 or a configuration error in logs; `describe` shows `Last State: Terminated` with the exit code; logs show missing environment variable, unreadable config file, invalid URL, or failed parse at startup.
- **Likely causes:** a new ConfigMap or Secret key missing; wrong env var name after a chart change; an invalid value type; a referenced file path changed.
- **Next checks:** `kubectl logs <pod> --previous` for the failed run; `kubectl describe pod` for `Last State` and events; compare the env block with the ConfigMap and Secret keys (names only, not values); check the rollout revision that introduced the change.
- **Confirm:** the failing log line names the missing or invalid key, and the key is absent or wrong in the referenced source.
- **Default severity for the finding:** high when production is affected.

### OPS-FAIL-002 — OOMKilled

- **Signals:** `describe` shows `Last State: Terminated, Reason: OOMKilled`, exit code 137; restart count rises under load; `kubectl top pod` shows memory near the limit before restart.
- **Likely causes:** memory limit below working set; a memory leak or unbounded cache; JVM heap configured larger than the container limit; a traffic spike with no concurrency limit.
- **Next checks:** the memory limit and request in the manifest; `kubectl top pod` history if metrics exist; application logs before the kill; the change log for heap or cache settings.
- **Confirm:** OOMKilled reason with memory near the limit before each kill. Leak claims need a trend over time.
- **Note:** exit code 137 is also produced by SIGKILL from other causes. Check the reason field.

### OPS-FAIL-003 — ImagePullBackOff and ErrImagePull

- **Signals:** status `ImagePullBackOff` or `ErrImagePull`; events show `Failed to pull image` with `unauthorized`, `not found`, `manifest unknown`, or timeout messages.
- **Likely causes:** tag does not exist (typo or unpublished build); private registry without `imagePullSecrets` or with expired credentials; registry rate limit; network policy blocking egress to the registry; wrong architecture.
- **Next checks:** image reference in the pod spec; events text for the exact error class; `imagePullSecrets` names on the service account and pod (names only); whether the tag exists in the registry (check through the registry tool available, not by pulling secrets).
- **Confirm:** the event message names the failing reason. "unauthorized" points to credentials, "not found" to the tag.

### OPS-FAIL-004 — Failed rollout

- **Signals:** `kubectl rollout status` does not complete; new ReplicaSet has pods not ready; Deployment condition `Progressing` false with reason `ProgressDeadlineExceeded`; old replicas still serving.
- **Likely causes:** new pods fail readiness; new pods fail startup (see OPS-FAIL-001); `maxUnavailable` and `maxSurge` leave no capacity to start new pods; PodDisruptionBudget blocks eviction of old pods; insufficient cluster resources.
- **Next checks:** `kubectl get rs` to compare old and new ReplicaSets; `describe deployment` conditions; `rollout history` for the revision; events for the new pods; the PDB status.
- **Confirm:** the first failing condition on new pods, with its event or log.
- **Remediation advice:** rollback to the previous revision (`kubectl rollout undo` as an advised step for a human), after confirming the previous revision was healthy.

### OPS-FAIL-005 — Probe failures

- **Signals:** events `Readiness probe failed` or `Liveness probe failed` with HTTP status or timeout; pods restart after a probe failure; pods not in endpoints while process is running.
- **Likely causes:** probe path or port wrong; probe timeout shorter than the real response time under load; liveness probe checks a downstream dependency that is down; startup slower than the liveness initial delay; probe hits an endpoint that requires authentication.
- **Next checks:** the probe definition (path, port, timeouts, thresholds); the endpoint response time from logs or a debug container with the same network; events for the exact probe error; whether the restart count increases only under load.
- **Confirm:** the probe error type matches the cause (connection refused means wrong port or process not listening; timeout means latency or wrong path; 4xx or 5xx means wrong path or application error).

### OPS-FAIL-006 — Pending pods and scheduling

- **Signals:** status `Pending`; events `FailedScheduling` with `Insufficient cpu`, `Insufficient memory`, `node(s) had untolerated taint`, `didn't match Pod's node affinity/selector`, `pod has unbound immediate PersistentVolumeClaims`, or `topology spread constraints`.
- **Likely causes:** requests larger than any node's free capacity; a taint without a toleration; an affinity rule that matches no node; unbound PVC or storage class mismatch; spread constraints with `DoNotSchedule` on a small cluster.
- **Next checks:** `describe pod` events text; node allocatable and allocated resources; node taints and labels; PVC status and storage class; the affinity and spread definitions.
- **Confirm:** the FailedScheduling message names the constraint. Compare the requested value with the largest free node.

### OPS-FAIL-007 — DNS resolution failure

- **Signals:** application logs show `no such host`, `name resolution failed`, `EAI_AGAIN`, or `ENOTFOUND` for in-cluster names; intermittent failures under load; failures only in one namespace.
- **Likely causes:** wrong service name or namespace in the connection string; CoreDNS pods unhealthy or overloaded; `ndots` causing excessive lookups; network policy blocking DNS egress to kube-dns; custom DNS configuration on the pod.
- **Next checks:** the connection string (host only); CoreDNS pod status and logs; whether the service exists in the namespace named (`get svc`); events for the CoreDNS deployment; a debug pod with DNS tools in the same namespace (read-only query only).
- **Confirm:** a query for the exact name fails from the affected pod and succeeds from a pod in a healthy namespace; or CoreDNS logs show errors or timeouts.

### OPS-FAIL-008 — Service has no endpoints

- **Signals:** `kubectl get endpoints` (or EndpointSlice) empty for a Service; clients receive connection refused; pods running but not ready.
- **Likely causes:** selector labels do not match pod labels; pods not ready (see OPS-FAIL-005); wrong target port name or number.
- **Next checks:** Service selector against pod labels; target port against container ports; readiness status of matching pods.
- **Confirm:** a selector that matches zero ready pods.

### OPS-FAIL-009 — Certificate expiry and TLS failures

- **Signals:** `x509: certificate has expired` or `certificate is not yet valid` in client or ingress logs; ingress returns a default certificate; cert-manager resources in `False` ready state; sudden failures at a fixed time of day.
- **Likely causes:** certificate not renewed (issuer failure, DNS challenge failing, rate limit); secret holding the certificate not updated; clock skew on the client; the certificate chain missing an intermediate.
- **Next checks:** the certificate's `notAfter` date from the served certificate (read the public certificate only, never a private key); cert-manager `Certificate` and `CertificateRequest` status and events; the Secret's creation time (names and metadata only); the issuer status.
- **Confirm:** the expiry date from the served certificate, and the failing renewal event.
- **Note:** never print private key material while checking certificates.

### OPS-FAIL-010 — Connection and timeout errors between services

- **Signals:** `connection refused`, `connection reset`, `i/o timeout`, `context deadline exceeded` in logs; errors correlate with deploys, scale events, or network policy changes.
- **Likely causes:** the upstream is not listening (see OPS-FAIL-008); upstream closing idle connections shorter than the client pool's idle timeout; a network policy change; upstream saturation; a sidecar or proxy configuration change.
- **Next checks:** upstream readiness and endpoints; client pool and timeout settings; network policies in the namespace; upstream latency and error metrics if available.
- **Confirm:** the error type and the timing relative to the change. "connection reset" after idle periods points to idle timeout mismatch.

### OPS-FAIL-011 — Evicted pods and node pressure

- **Signals:** pods in `Evicted` state; events `The node was low on resource: memory` or `ephemeral-storage`; node conditions `MemoryPressure` or `DiskPressure`.
- **Likely causes:** no memory or storage limits for noisy workloads; large log output filling ephemeral storage; burst usage beyond node capacity.
- **Next checks:** node conditions; which pods use the most resources (`top`); ephemeral storage limits; log volume.
- **Confirm:** the node pressure condition at the time of eviction.

### OPS-FAIL-012 — Permission denied from the Kubernetes API

- **Signals:** application logs show `forbidden` or `User "system:serviceaccount:..." cannot list resource`; operators or controllers stuck.
- **Likely causes:** service account lacks the role; RoleBinding in the wrong namespace; a chart change that changed the service account name.
- **Next checks:** the service account name in the pod spec; RoleBindings and Roles in the namespace (names and verbs); `kubectl auth can-i` for the service account if permitted.
- **Confirm:** the forbidden message names the verb, resource, and service account.

## How to apply in review

1. Map the symptom to one or more families above using the signal list.
2. Run the next checks in order of cost. Stop when one hypothesis is confirmed.
3. Record each check with its command shape and the result count, and label facts and inferences.
4. Do not print Secret values, certificate private keys, or full environment dumps.
5. For each confirmed cause, give the remediation advice and a rollback, following `troubleshooting-method.md`.
