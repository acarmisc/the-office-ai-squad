# 0005 — Sandbox backend: one ephemeral pod per invocation

- Status: accepted
- Date: 2026-11-01

## Context

`pam` (implementer mode) clones a repository, runs the project's own checks, edits files and
pushes a branch with no human approval step. The repository content is untrusted: its
`package.json` scripts, Makefile targets and test code run inside the sandbox. The sandbox must
therefore hold no agent secrets, reach only the git host and the package registry, and be
destroyed after each invocation.

## Decision

- `Sandbox` is a protocol (`_common/sandbox/base.py`). Two backends share one base class that
  owns policy, credential and patch logic; backends provide only process, file and cleanup
  primitives.
- **`KubernetesJobSandbox` (cluster default):** one pod per invocation, created in the sandbox
  namespace from `sandbox-node`, driven through the exec API (`connect_get_namespaced_pod_exec`
  via `kubernetes.stream.stream`). The pod runs as uid 10002 with `runAsNonRoot`, a read-only root
  filesystem, all capabilities dropped, `RuntimeDefault` seccomp, `automountServiceAccountToken:
  false`, `enableServiceLinks: false`, and `emptyDir` volumes at `/workspace` and `/tmp`.
  `activeDeadlineSeconds` is a hard stop. `destroy()` deletes the pod with grace 0 and is called
  from `__exit__`, so a `with` block cleans up when the body raises.
- Every command runs as `env -i -C <cwd> PATH=… HOME=… … timeout --kill-after=5 <secs> <argv>`.
  The environment is cleared inside the container, so nothing from the image or the pod spec
  leaks into commands.
- **`LocalProcessSandbox` (development and tests only):** a temp directory on the host, a scrubbed
  environment, a new process group killed on timeout, `RLIMIT_CPU` and `RLIMIT_FSIZE` on Linux,
  and output captured to temp files. It provides no container isolation and must not be used in
  the cluster.
- Command policy (`policy.py`): an allow-list of executables. Shells, interpreters and
  `env`/`xargs`/`find`-style wrappers are never allowed, not even through `extra`. `git`
  subcommands are an allow-list; `clone` and `push` are refused in `exec` (they have dedicated
  methods that check URLs and branches), and dangerous options (`--upload-pack`, `--output`,
  `--no-index`, `--textconv`, …) are refused. `npm`/`pnpm`/`yarn` may run `run`, `test` and
  install subcommands only, with `--ignore-scripts` forced on installs. `npx` is forced to
  `--no` and must name a binary that exists locally. `node` runs script files or `--version`
  only. `make` and `just` accept plain target names only.
- Credentials for `clone` and `push` (`credentials.py`) are passed through `GIT_ASKPASS`. The
  askpass script reads the token from a private file (mode 0600) in a private directory (mode
  0700). Only the paths and the username enter the environment. The directory is removed in a
  `finally`. Credentials are refused for any host other than the one they were issued for, and
  for non-http(s) remotes.
- Git runs with `GIT_CONFIG_GLOBAL=/dev/null`, `core.hooksPath=/dev/null`, and
  `GIT_ALLOW_PROTOCOL` limited to the configured schemes (https by default).
- Push never uses `--force` or `+` refspecs, and refuses protected branches (`main`, `master`,
  `develop`, `release/*` by default) and malformed names.
- Trajectory monitor (`trajectory.py`): `MonitoredSandbox` wraps any `Sandbox` and counts command
  attempts, including denied ones, against the command budget. It enforces the wall-clock budget
  and token budget, records an audit entry per command (argv, exit code, duration, a 16-hex-char
  SHA-256 of the output, and the timeout flag, but never the output), raises `LoopDetectedError`
  when the same argv fails with the same output three times, and emits one JSON log line per
  command with the tool name, status and duration only.

### Alternatives considered

- **Sidecar container with a shared volume** in the agent pod: simpler to wire, but the agent
  and the untrusted repository code share a pod, network namespace and service account token,
  and per-invocation isolation is weak. Rejected.
- **Kubernetes Job instead of a bare Pod:** Jobs support `ttlSecondsAfterFinished`, which Pods
  do not. Chosen against for now: exec and per-pod status are simpler on a Pod. Known cost:
  a pod orphaned by a crashed agent lingers until it is reaped. `activeDeadlineSeconds` bounds
  it but does not delete it. A Job-based variant is the follow-up.
- **Host execution only:** not acceptable for the cluster.

## Deviations from the brief

- **Token transport:** the brief suggested `SQUAD_GIT_TOKEN` in the git process environment. The
  token is instead written to a private file for both backends. In the cluster an environment
  assignment in the exec command would be recorded in the API server's audit log, and the token
  would then leak there. The askpass script reads the file.
- **`clone` ref:** only branch and tag names are accepted (`--branch`). A commit SHA is refused,
  because a shallow clone cannot check one out reliably.
- **`clone` and `push` return `None`** as the protocol specifies. The monitor audits them
  as `("git", "clone", ref)` and `("git", "push", branch)` without the URL.
- **`diff()`** runs `git add --intent-to-add --all` so that new files appear in the diff. It
  changes the index, not the working tree.
- **`ttl_seconds_after_finished`** is stored on the backend but not applied, because the Pod
  API has no such field. See the Job follow-up above.
- **Exit code 124:** a command that exits with 124 on its own is reported as timed out, because
  `timeout(1)` uses the same code.

## Consequences

- Helm must render, for `pam` only: a Role in the sandbox namespace (pods create/get/list/delete/
  watch, `pods/exec` create, `pods/log` get), a RoleBinding, and a sandbox NetworkPolicy that
  allows DNS and the configured git or registry CIDRs only. This already exists in
  `rbac-sandbox.yaml` and `networkpolicy.yaml`.
- The namespace must exist beforehand with the restricted Pod Security label.
- File writes need the v5 exec channel protocol (Kubernetes 1.30+). On a v4-only API server
  writes fail closed with a clear error.
- Repository scripts run arbitrary code inside the sandbox by design (that is how tests run).
  The protections are the absence of secrets and credentials in that environment, the network
  allow-list, the resource and deadline limits and the destruction of the pod. A repository could
  still read its own checkout and exhaust its own quota.
- `LocalProcessSandbox` runs repository code on the host with the caller's file access. It is a
  development tool only, and `build_sandbox("local")` is meant for dev and tests.
- Output is capped (64 KiB per stream by default, head plus tail). Secret redaction runs after
  capture, so a secret split across the cut is not redacted. Secrets are never placed in
  arguments or output in the first place.
