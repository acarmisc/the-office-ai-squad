# 0007 — No approval gate for pam (implementer mode)

- Status: accepted
- Date: 2026-11-01

## Context

The brief (§2.4, §9) requires `pam` to implement a task and open a merge or pull request in a
single invocation, without a human approval step before the change request exists. The
change request is the review point: humans review and merge it through the normal process.
The agent must never merge.

Without a gate, every control that a human would otherwise apply before a write must be
enforced by the platform. This ADR records which controls replace the approval step.

## Decision

`pam` has no plan-approval, confirmation or "publish" tool, and the runtime has no pause point
between planning and publishing. The tool list (`code_squad/pam/__init__.py`) contains no tool
named approve, confirm or merge. A test (`tests/pam/test_policy.py`) fails if one appears.

The following controls compensate for the missing gate. Each one is enforced in code, not only
in the prompt.

1. **Isolation.** Repository code (package scripts, test code, install scripts) runs in the
   sandbox only (ADR 0005). The Kubernetes backend runs one pod per invocation with no service
   account token, a read-only root filesystem and a restricted network policy. The local backend
   is for development and tests only.
2. **Command allow-list.** `run_command` and the check runner pass through the sandbox policy:
   no shells, interpreters, wrappers or network tools. Git `clone` and `push` are refused in
   `exec`. Install scripts are disabled with `--ignore-scripts`.
3. **Scrubbed environment and scoped credentials.** The sandbox environment never includes
   agent secrets. Git credentials are passed through an askpass file for the single `clone` or
   `push` call, only to the configured host and only over http(s). Local file remotes never
   receive credentials. Output is redacted for the token before it reaches the model.
4. **Protected branches.** `start_work` and `push_branch` refuse the base branch, any branch that
   matches the sandbox defaults (`main`, `master`, `develop`, `release/*`), and any branch the
   provider reports as protected. Pushes never force and never use `+` refspecs.
5. **Protected paths.** `commit` refuses changes to CI files, lockfiles and other paths listed
   in `implementer.protected_paths`, unless the model passes `protected_paths="allow"`. When it
   does, those paths are recorded in the run result and listed in the change request body.
6. **No merge capability.** No tool calls a merge API, approves a change request or changes
   branch protection.
7. **Change request as the review point.** `open_change_request` renders the description from
   the task, the check results and the protected-path list. It uses the configured labels
   (default `ai-generated`), reviewers and assignees. `implementer.mr_draft` (default `false`)
   lets a project open drafts.
8. **Dry-run.** When posting is disabled, `push_branch` and `open_change_request` are cancelled
   by the policy hook before they run. Local work still happens and nothing leaves the sandbox.
9. **Trajectory budgets.** The sandbox monitor caps commands (60 per run) and wall-clock time
   (`implementer.sandbox.timeout_seconds`). It halts the run when the same failing command
   repeats three times with identical output. A halted run is reported as incomplete, and the
   runner overrides a complete status to incomplete.
10. **Audit.** Every sandbox command is recorded with its argv, exit code, duration and a
    16-character digest of its output. Only tool names, status and duration reach the logs.
11. **Untrusted input.** Task text, repository files, diffs, command output and skills are
    wrapped as untrusted blocks. The prompt states that they are data. The write tools accept
    no branch name or force flag from the model. `push_branch` takes no arguments at all.
12. **Destruction.** `run_pam` destroys the sandbox in a `finally` after every invocation, even
    when the model fails mid-run. Cleanup failures are logged and do not hide the result.

## Alternatives considered

- **Plan approval before the first write.** Rejected by the requester (§2.4). It would also
  need a resumable run, which the platform does not have.
- **Draft-only change requests by default.** Kept as a per-project option (`mr_draft`), not the
  default. A draft still runs the same CI, so it adds little review protection, and it hides
  the work from the normal review queue.
- **Publish-after-review by a second agent.** Rejected for this milestone. It doubles the cost
  per change and still needs a human at the merge step.

## Consequences

- A change request can exist with failing checks. The description states which checks fail,
  and the run is reported as complete with the failure in its data. The reviewer decides.
- A protected-path change needs the model to ask for `"allow"`. The change request then makes it
  visible. Projects that want a human to approve such changes must configure their own review
  rules on the protected paths.
- Dry-run cannot show the exact change request arguments. The policy hook cancels the tool
  before its body runs, so the model must state the intended title and description in its
  finish summary and plan.
- A repository's own scripts still run arbitrary code inside the sandbox by design (ADR 0005).
  The protections above limit what that code can reach. They do not limit what it can compute.
- A halted run calls the model once more, because the runtime retries a missing `finish()`.
  That retry cannot run tools that change anything.
