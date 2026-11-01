# Local validation of the deployment artifacts (M10)

This page records what was run to validate the container image, the compose demo, the
kind demo and the Helm chart, the commands used, the observed output, and what could
not be run. It covers brief section 15 items 2 to 4. Nothing here contains a secret: the
only key is the demo placeholder `fake-key-for-local-demo`.

## Environment

| Item | Value |
| --- | --- |
| Host | Linux 6.18 (Firecracker VM), cgroup v1 host |
| Docker | server 29.9.2, Compose v5.6.1 |
| kind | v0.24.0 (node image `kindest/node:v1.31.0`) |
| kubectl / helm / kubeconform | v1.31.2 / v3.16.3 / v0.6.7 |

The sandbox routes outbound HTTPS through a TLS-intercepting proxy, so `uv sync` inside a
plain `python:3.12-slim` build fails with `UnknownIssuer`. Local builds therefore use a
base image that trusts the proxy CA:

```sh
scripts/local_ca_base.sh /root/.ccr/ca-bundle.crt        # builds cs-local/python:3.12-slim-ca
PYTHON_IMAGE=cs-local/python:3.12-slim-ca docker compose -f deploy/compose.yaml build
```

This is for local verification only. The committed `deploy/Dockerfile` is unchanged and
CI uses the default `PYTHON_IMAGE=python:3.12-slim`. The first pull of
`python:3.12-slim` hit a Docker Hub 429 and succeeded on retry.

## 1. Compose demo: passed

```sh
docker compose -f deploy/compose.yaml up -d
scripts/smoke_test.sh compose
docker compose -f deploy/compose.yaml down
```

All seven containers reached `healthy` (the fake LLM through its `/health` check, the
agents through `/ping`). The smoke test output:

```text
--- michael http://localhost:8081
PASS michael: status=complete verdict=comment findings=0 tool_calls={"finish": 1, "read_knowledge": 1} posted_notes=0 posted_discussions=0
--- jim http://localhost:8082
PASS jim: status=complete verdict=comment findings=0 tool_calls={"finish": 1, "read_knowledge": 1} posted_notes=0 posted_discussions=0
--- angela http://localhost:8083
PASS angela: status=complete verdict=comment findings=0 tool_calls={"finish": 1, "read_knowledge": 1} posted_notes=0 posted_discussions=0
--- dwight http://localhost:8084
PASS dwight: status=complete verdict=comment findings=0 tool_calls={"finish": 1, "read_knowledge": 1} posted_notes=0 posted_discussions=0
--- darryl http://localhost:8085
PASS darryl: status=complete verdict=comment findings=0 tool_calls={"finish": 1, "read_knowledge": 1} posted_notes=0 posted_discussions=0
--- pam http://localhost:8086
PASS pam: status=complete verdict=comment findings=0 tool_calls={"finish": 1, "read_knowledge": 1} posted_notes=0 posted_discussions=0
smoke compose: all 6 agents passed
```

The fake LLM log recorded 13 chat-completion requests for this run. A negative check with
one unreachable base URL exits 1 with `FAIL michael: GET /ready did not return 200 within 4s`.

### Re-run after ADR 0013 (operational readiness)

Run on 2026-11-01 against the working tree that contains ADR 0013, with the same CA base image. The compose file now sets
`SQUAD_ALLOW_UNAUTHENTICATED=1` explicitly, because `/invocations` refuses every request without a token. All six agents
passed `scripts/smoke_test.sh compose` (`smoke compose: all 6 agents passed`). The scripted dry-run client
`scripts/trial_review.sh http://localhost:8081 platform/example-app 123` returned `incomplete` with
`VCS unavailable for this run`, which is expected without a VCS, and posted nothing.

## 2. kind demo: not runnable in this environment

`deploy/kind/kind-up.sh` was run as committed, with the `IMAGE` and `PYTHON_IMAGE`
overrides. Cluster creation fails in `kubeadm init`:

```text
 ✗ Starting control-plane
ERROR: failed to create cluster: failed to init node with kubeadm: command "docker exec --privileged code-squad-control-plane kubeadm init --config=/kind/kubeadm.conf --skip-token-print --v=6" failed with error: exit status 1
```

The kubelet and containerd logs inside the node show the same failure for every pod
sandbox (etcd, kube-apiserver, kube-controller-manager, kube-scheduler):

```text
RunPodSandbox ... failed to create containerd task: failed to create shim task:
OCI runtime create failed: runc create failed: unable to start container process:
can't get final child's PID from pipe: EOF: unknown
```

Diagnosis, to narrow the cause:

- The default kind config (systemd cgroup driver) and a cgroupfs variant
  (`KubeletConfiguration cgroupDriver: cgroupfs`, `SystemdCgroup = false`) fail the same way.
- Inside a retained node, `ctr run` of the pause image succeeds with the default
  runtime, with `rprivate` and `rshared` bind mounts, and under a `kubepods` cgroup parent.
  So runc itself works in this VM. The failure is specific to the kubelet's pod-sandbox
  setup, and was not isolated further.

This is treated as an environment restriction (nested containers in this VM), not a
defect in the kind configuration, and the brief's fallback (section 15.3) applies. The
probe clusters were deleted, and `kind get clusters` is empty. The kind scripts are
written and syntax-checked (`bash -n`), but the kind path itself has not been executed
to a Ready cluster. The `kind-smoke.sh` port-forward and readiness logic is untested.

## 3. Helm chart fallback: passed

```sh
helm lint deploy/helm/code-squad
for f in deploy/helm/code-squad/values-examples/*.yaml; do
  helm lint deploy/helm/code-squad -f "$f"
  helm template t deploy/helm/code-squad -f "$f" | kubeconform -strict -summary -ignore-missing-schemas
done
helm template t deploy/helm/code-squad | kubeconform -strict -summary -ignore-missing-schemas
```

Observed:

```text
[INFO] Chart.yaml: icon is recommended
1 chart(s) linted, 0 chart(s) failed
default values:            Summary: 29 resources found in 1 file - Valid: 29, Invalid: 0, Errors: 0, Skipped: 0
egress-proxy-airgapped:    Summary: 31 resources found in 1 file - Valid: 31, Invalid: 0, Errors: 0, Skipped: 0
external-secrets:          Summary: 31 resources found in 1 file - Valid: 31, Invalid: 0, Errors: 0, Skipped: 0
github-app:                Summary: 32 resources found in 1 file - Valid: 32, Invalid: 0, Errors: 0, Skipped: 0
gitlab-only:               Summary: 34 resources found in 1 file - Valid: 34, Invalid: 0, Errors: 0, Skipped: 0
minimal-kind:              Summary: 20 resources found in 1 file - Valid: 20, Invalid: 0, Errors: 0, Skipped: 0
multi-provider:            Summary: 34 resources found in 1 file - Valid: 34, Invalid: 0, Errors: 0, Skipped: 0
production-ha:             Summary: 49 resources found in 1 file - Valid: 48, Invalid: 0, Errors: 0, Skipped: 1
```

The one skipped object in `production-ha` is the `ServiceMonitor`, whose CRD schema is not
bundled with kubeconform (`-ignore-missing-schemas`).

Restricted Pod Security checks on the rendered Deployments (grep, not a PSS validator):
for the default and `production-ha` renders, all 6 Deployments set `runAsNonRoot: true`,
`readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, `drop: [ALL]` and
`seccompProfile: RuntimeDefault`.

## Multi-arch build

`docker buildx build --platform linux/amd64,linux/arm64 -f deploy/Dockerfile` succeeded for
both platforms (arm64 through QEMU emulation, `tonistiigi/binfmt --install arm64`) with a
`docker-container` builder. Because the validation environment intercepts TLS, the base
image was a local multi-arch copy of `python:3.12-slim` that trusts the proxy CA, passed as
`--build-arg PYTHON_IMAGE=...` and served from a throwaway local registry. The committed
`deploy/Dockerfile` was unchanged. The arm64 image was built, not run.

## Not done

- Live kind smoke (`deploy/kind/kind-smoke.sh`): blocked by the kubeadm failure above.
- The NetworkPolicy, RBAC and sandbox paths were not exercised at runtime (none of them
  run in the compose demo or the kind values).
- `just check` as a whole was not run on this branch; the parts in scope for this
  milestone were run (see the milestone report).
