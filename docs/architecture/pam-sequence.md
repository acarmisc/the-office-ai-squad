# pam sequence: task to change request

`pam` runs in two modes. In **advisor** mode (the default) it reads the repository and returns a
plan, with no write of any kind. In **implementer** mode it implements the task, runs the
repository's own checks, pushes a branch and opens a change request, in one invocation. There
is no approval step between planning and the change request (see
[ADR 0007](../decisions/0007-no-approval-gate-for-pam.md)). The controls that replace that step
are listed under the diagram.

## Sequence

```mermaid
sequenceDiagram
  autonumber
  participant Caller as Caller (webhook, CI, CLI)
  participant P as pam runtime
  participant SBX as Sandbox pod (or local process in development)
  participant VCS as VCS provider
  participant Model as LLM gateway

  Caller->>P: POST /invocations (mode implementer, project, prompt or task)
  P->>VCS: read task (get_task) and repository files (read only)
  P->>Model: plan and implementation turns (untrusted content wrapped)
  P->>SBX: start_work: clone base branch, create pam/<task-key>-<slug>
  loop small steps until checks pass or the budget ends
    P->>SBX: write_file or apply_patch, sandbox_read or sandbox_diff
    P->>SBX: run_checks (repository check recipe or package scripts)
    SBX-->>P: pass or fail, first relevant error line
  end
  P->>SBX: commit (refuse changes to protected paths unless "allow")
  P->>SBX: push_branch (no arguments; never a protected branch; never forced)
  SBX->>VCS: git push over HTTPS, credentials from an askpass file
  P->>VCS: open_change_request (labels, reviewers, assignees, draft as configured)
  VCS-->>P: change request URL
  P->>SBX: destroy (in a finally block, even after an error)
  P-->>Caller: InvocationResult with verdict, summary and data (branch, MR URL, checks)
```

In dry run (`post: false`), `start_work`, edits, checks and `commit` run as usual. `push_branch`
and `open_change_request` are refused by the posting gate before they run, and the finish summary
names the branch, commit message and change request title that would have been used.

## Controls that replace the approval step

These are enforced in code. The prompt also asks for them, but the prompt is not the control.

| Control | Where it lives | Effect |
| --- | --- | --- |
| Isolation | Sandbox backend (`_common/sandbox/`) | Repository code runs in its own pod with no service account token, a read-only root filesystem, dropped capabilities and a restricted network policy. |
| Command allow-list | `_common/sandbox/policy.py` | No shells, interpreters or wrappers. Git `clone` and `push` are refused in `run_command`. Installs run with `--ignore-scripts`. |
| Scoped credentials | `_common/sandbox/credentials.py` | Git credentials are written to a private file for one `clone` or `push`, only for the configured host and only over HTTPS. |
| Protected branches | `start_work`, `push_branch`, sandbox defaults | `main`, `master`, `develop`, `release/*` and any branch the provider reports as protected are refused. No force push. |
| Protected paths | `commit` | CI files, lockfiles and `implementer.protected_paths` are refused unless the model passes `"allow"`. Such paths are listed in the change request body. |
| No merge capability | Tool list | No tool approves, merges or changes branch protection. |
| Change request as review point | `open_change_request` | Description rendered from the task, check results and protected-path list. Labels default to `ai-generated`. Draft only when `implementer.mr_draft` is true. |
| Dry run | Posting gate and policy hook | `push_branch` and `open_change_request` are cancelled before they run. |
| Budgets | `MonitoredSandbox` (`trajectory.py`) | Up to 60 commands per run, wall-clock limit from `implementer.sandbox.timeout_seconds`, and a halt after the same failing command repeats three times with identical output. A halted run is `incomplete`. |
| Audit | Trajectory monitor | Every command: argv, exit code, duration and a 16-character digest of its output. Output itself is not logged. |
| Untrusted input | Prompt and `untrusted.py` | Task text, repository files, command output and skills are data. The write tools take no branch name or force flag from the model. |
| Destruction | `run_pam` | The sandbox is destroyed after every invocation. A cleanup error is logged and does not replace the result. |

## Checks

`run_checks` uses `implementer.check_commands` when set. Otherwise it detects the repository's
check recipe (for example `just check`) or package scripts for lint, typecheck, test and build.
A repository with no detectable checks makes `run_checks` report that no checks were found. The
prompt tells the model not to disable or skip tests to reach green; the tool policy does not check
that.

## Results

The prompt asks for `comment` when the change request was opened and `request_changes` when a check
still fails or the task cannot be completed; the runtime does not enforce that mapping. `status` is `complete` only when the run
finished with a result and no halt. `data` carries the branch, the change request URL when one
exists, the check results, the changed files and `protected_paths_touched`.

## What is not covered

- A repository's own scripts run arbitrary code inside the sandbox. The controls limit what that
  code can reach. They do not limit what it can compute, and the pod can use its own CPU and
  memory quota until the deadline.
- The Kubernetes sandbox needs the sandbox namespace to exist with the restricted Pod Security
  label, and the cluster must support the exec protocol that file writes use (Kubernetes 1.30 or
  later). See [ADR 0005](../decisions/0005-sandbox-backend.md).
- The pod TTL (`SANDBOX_TTL_SECONDS_AFTER_FINISHED`) is stored but not applied: pods have no TTL
  field. An orphaned pod is removed by its `activeDeadlineSeconds` but not deleted.
- The local process sandbox provides no container isolation. Do not run `pam` on the local backend
  in a cluster. See [Hardening](../security/hardening.md).
