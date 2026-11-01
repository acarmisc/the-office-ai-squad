# pam: frontend engineer

`pam` is a senior React engineer. In **advisor** mode it reads a repository and answers design and
implementation questions with a plan, without writing anything. In **implementer** mode it takes a
task, implements it in an isolated sandbox, runs the repository's own checks, pushes a branch and
opens a change request. The change request is the review point: a human reviews and merges it, and
the squad never merges.

There is no approval step between planning and the change request. This is deliberate
([ADR 0007](../decisions/0007-no-approval-gate-for-pam.md)). The controls that replace it are in
[pam sequence](../architecture/pam-sequence.md#controls-that-replace-the-approval-step).

| Item | Value |
| --- | --- |
| Role | frontend-dev |
| Modes | `advisor` (default), `implementer` |
| Default model | `sonnet-5-5` |
| Max tokens per call | 16384 |
| Max model turns | 60 |
| Writes externally | `push_branch` and `open_change_request`, only in implementer mode and only when posting is enabled |

## Triggers

- `POST /invocations` with `mode: "implementer"` and a `project`, and a task reference in `target` or
  the prompt. Typically from a tracker integration.
- A webhook issue assignment to the bot starts an implementer run through `michael`, when the issue
  does not carry a skip label and the user who assigned it is in `trigger.allowed_assigners`. An empty list means nobody.
  A `/squad implement` comment on an issue does the same, subject to `trigger.allowed_commenters`.
- Advisor mode: any call without a mode, or with `mode: "advisor"`.

## Tools and policy class

| Tool | Class | Mode | Purpose |
| --- | --- | --- | --- |
| `get_task` | read | both | Task text and acceptance criteria from the issue tracker. |
| `read_file`, `search_repo`, `list_tree` | read | both | Repository reads at the base branch. |
| `get_project_skills`, `load_skill`, `read_knowledge` | read | both | Guidance. |
| `sandbox_read`, `sandbox_list`, `sandbox_diff` | read | implementer | Read the working copy, including uncommitted edits. |
| `start_work` | local mutation | implementer | Clone the base branch into the sandbox and create `pam/<task-key>-<slug>`. |
| `write_file`, `apply_patch` | local mutation | implementer | Edit the working copy. |
| `run_command` | local mutation | implementer | Run an allowed command (no shell). |
| `run_checks` | local mutation | implementer | Run the repository's checks. |
| `commit` | local mutation | implementer | Commit with the configured template. Refuses protected paths unless `"allow"`. |
| `push_branch` | external write | implementer | Push the working branch. Takes no arguments. |
| `open_change_request` | external write | implementer | Open the change request from the rendered description. |
| `finish` | read | both | Ends the run. |

In advisor mode the mutating tools answer "not available in advisor mode". The advisor writes a plan in
`finish` with `data.plan` as a list of steps and an empty `findings` list.

## Implementer workflow

1. Read the task and the acceptance criteria. If the task is ambiguous, choose the most conservative
   reading and say so in the change request.
2. Explore the repository read-only and load the skills.
3. Plan: files to touch and tests to add.
4. `start_work(task_key, summary)`.
5. Edit in small steps and check the working copy.
6. `run_checks()`; fix and repeat until green. Never disable or skip a test to pass.
7. `commit(message, "refuse")`, `push_branch()`, `open_change_request(title, what, why, how_tested, risks)`.
8. `finish` with the change request URL from the tool result.

The description has sections for what changed, why, how it was tested and the known risks. Risks say
"none known" when there are none.

## Sandbox

- Local development uses the local process sandbox. In a cluster, `SANDBOX_NAMESPACE` selects the
  Kubernetes sandbox: one pod per invocation from `sandbox-node`, running as uid 10002, with a
  read-only root filesystem, dropped capabilities, `RuntimeDefault` seccomp, no service account token,
  `emptyDir` volumes for `/workspace` and `/tmp`, a deadline and a restricted network policy.
- Commands are allow-listed: git (no clone or push through `run_command`, and no dangerous options),
  `npm`/`pnpm`/`yarn` `run`, `test` and `install` (scripts ignored), `npx` for a local binary, `node`
  for a script file or `--version`, and `make` or `just` for plain target names. Shells, interpreters
  and wrappers are refused.
- The model cannot pass a branch name or a force flag. Git credentials are used only for the clone and
  the push, through an askpass file.
- Output is capped per stream. Each command is audited with a digest of its output.

## Outputs

The smoke-stub output below shows the result shape only. It was produced by the scripted model of the
offline fake LLM in advisor mode, without a repository. A real advisor result carries the plan in
`data.plan`, and a real implementer result carries the branch, the change request URL and the checks.

```json
{
  "agent": "pam",
  "status": "complete",
  "verdict": "comment",
  "summary": "Smoke run: frontend engineer completed its scripted pass. No changes were made and nothing was published.",
  "findings": [],
  "stats": {"iterations": 2, "input_tokens": 20, "output_tokens": 10, "tool_calls": {"read_knowledge": 1, "finish": 1}},
  "posted": {"notes": 0, "discussions": 0, "status": null, "urls": []},
  "warnings": []
}
```

## Knowledge

`pam` uses the shared React pack (`react/*`, see [jim](jim.md#knowledge)) and the `pam/knowledge`
directory, which has a README only. Topics that matter most: `react/hooks-and-effects`,
`react/state-and-data-fetching`, `react/component-design`, `react/forms-and-validation`,
`react/accessibility`, `react/testing`, `react/project-structure`. The prompt uses them only where the
repository has no pattern to copy.

## Configuration that affects pam

Everything is under `implementer` unless noted.

| Key | Default | Effect |
| --- | --- | --- |
| `implementer.branch_template` | `pam/{task_key}-{slug}` | Branch name. |
| `implementer.commit_template` | `feat: {summary}` | Commit message. |
| `implementer.mr_title_template`, `mr_body_template` | `{task_key}: {summary}`; sections What, Why, How tested, Risks | Change request title and body. |
| `implementer.labels` | `[ai-generated]` | Labels added to each change request. |
| `implementer.reviewers`, `assignees` | `[]` | Requested on each change request. |
| `implementer.mr_draft` | `false` | Open change requests as drafts. Nothing waits for a human either way. |
| `implementer.check_commands` | `null` | Commands `run_checks` runs. Null detects them from the repository. |
| `implementer.git_identity` | `pam (code-squad)` | Commit author. |
| `implementer.protected_paths` | CI files, `.github/**`, lockfiles | Commits that touch them are refused unless `"allow"`. Lower layers may add. |
| `implementer.allowed_protected_paths` | `[]` (organisation only) | Globs pam may change although `protected_paths` matches them. A repository cannot allow a protected path. |
| `implementer.extra_executables` | `[]` (organisation only) | Extra executables on the sandbox allow-list. |
| `implementer.sandbox.timeout_seconds` | `1800` | Wall-clock limit of one run. Capped by `limits.max_wall_clock_seconds`. |
| `implementer.sandbox.image`, `cpu`, `memory` | see reference | Not read at run time. The chart sets `SANDBOX_IMAGE` and `SANDBOX_RESOURCES_JSON`. |
| `agents.pam.enabled`, `model`, `max_tokens`, `max_iterations` | built-in | As for other agents. |
| `SANDBOX_NAMESPACE` (environment) | unset | When unset, pam uses the local process sandbox. See the warning below. |

> **Refusal.** The sandbox backend is chosen only by `SANDBOX_NAMESPACE`. When it is unset, pam refuses to start
> unless `ALLOW_LOCAL_SANDBOX=1` is set, so a cluster deployment cannot silently run repository commands in the pam
> container. With `ALLOW_LOCAL_SANDBOX=1`, the local process backend runs them without container isolation. The chart
> sets `SANDBOX_NAMESPACE` when `sandbox.enabled` is true. The kind demo turns the sandbox off and sets
> `ALLOW_LOCAL_SANDBOX` through its own values. Do not run `pam` this way outside a disposable test cluster. See
> [Hardening](../security/hardening.md#pam-controls).

## Limits

- Up to 60 commands per run, and a wall-clock limit. A halted run is reported as `incomplete`, even when
  the model asked to finish as complete.
- Repository scripts run arbitrary code inside the sandbox. The sandbox limits what that code can
  reach. It does not limit what the code computes.
- File writes into a Kubernetes sandbox need the v5 exec protocol (Kubernetes 1.30 or later).
- Protected branches and forced pushes are refused. The squad cannot push to `main`.
- Task text comes from the VCS issue tracker by default. When the `JIRA_BASE_URL` variable is set and the Jira
  token secret `jira-api-token` is available, Jira is used instead, read-only.

## Known weaknesses

- Plans for large tasks can exceed the model's turn budget. Split the task.
- Check detection is heuristic when the repository has no check recipe. Set `check_commands` for
  repositories with unusual layouts.
- The change request can exist with failing checks. The description says which checks fail, and the
  reviewer decides. This is the trade-off of having no approval step.

## How to evaluate

The eval set does not include the pam scenario in the brief (a small feature added to the fixture app,
which must pass lint, typecheck and tests and then produce a change request on the fake VCS). The
unit tests in `tests/pam/` cover the policy, the protected-path rules, the advisor refusals and the
workflow with a fake sandbox. Run them with `just test tests/pam`.
