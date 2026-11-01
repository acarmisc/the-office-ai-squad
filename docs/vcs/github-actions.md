# GitHub Actions review (in-runner mode)

A pull request can be reviewed without a deployed service. One step in the repository's workflow runs the published
image inside the job, reads the pull request with the job's `GITHUB_TOKEN`, and reports the review. This page covers when
to use that mode, how to set it up, what it does and does not do, and how to gate merges. The deployed service
(webhooks, several agents, the orchestrator) is described in [GitHub](github.md) and the [Helm chart](../deployment/helm.md).

## When to use which mode

| | In-runner mode (this page) | Deployed service |
| --- | --- | --- |
| What runs it | A step in the repository's workflow, on a GitHub-hosted or self-hosted runner | Pods in your cluster, reached over HTTP and webhooks |
| Infrastructure | None beyond an LLM gateway URL and key | A cluster, the chart, ingress, secrets, monitoring |
| Trigger | `pull_request` events, one run per event | Webhooks, or `POST /invocations` |
| Agents | One per step: `jim`, `angela`, `dwight`, `darryl`, or `michael` | All six, with `michael` orchestrating the specialists |
| `michael` | Runs in the same job, calling the specialists in process | Calls the specialists over HTTP |
| `pam` | Not available | Available when its sandbox is deployed |
| Cost and latency | Pays for runner minutes on each pull request; no standing cluster | Pays for the cluster; no minutes per pull request |
| Forks | Skipped (no secrets reach fork pull requests) | Depends on the trigger; see [ingress and webhooks](../deployment/ingress-webhooks.md) |
| Results | Step summary, step outputs, a JSON result file, and the same comments and status as the service | Same, plus the API and metrics |

Use in-runner mode to start: one repository, one React or Java team, no cluster. Move to the service when you need
webhooks, several agents on the same change, `pam`, metrics, or a shared deployment across many repositories.

## Setup checklist

- [ ] Choose the agent for the repository: `jim` for React and TypeScript, `angela` for Java, `dwight` for security,
      `darryl` for CI and deployment. Copy `examples/github/github-actions-review-jim.yml` into
      `.github/workflows/code-squad-review.yml` and change the agent if needed.
- [ ] Add the repository variable `LLM_BASE_URL` (the LiteLLM gateway, for example `https://llm.example.com/v1`).
- [ ] Add the repository secret `LLM_API_KEY`.
- [ ] Leave the variable `SQUAD_POST` unset for the first pull requests. The review is then a dry run.
- [ ] Check the workflow permissions. The job needs `contents: read`, `pull-requests: write` and `statuses: write`. The
      example sets them. An organisation that restricts the default `GITHUB_TOKEN` must allow them for this workflow.
- [ ] Pin the action. The example uses `acarmisc/the-office-ai-squad@v0.1.0`; a full commit SHA with the tag in a
      comment is stricter.
- [ ] Make the image pullable. The default image is `ghcr.io/acarmisc/code-squad`. A private package needs a pull
      credential on the runner, or the package made public (see [troubleshooting](#troubleshooting)).
- [ ] Run one dry-run review on a real pull request and read the step summary. When the findings are right, set
      `SQUAD_POST` to `true`.

## The step

The whole integration is one step. The example adds the job-level guards that the step relies on:

```yaml
permissions:
  contents: read
  pull-requests: write
  statuses: write

jobs:
  review:
    if: github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    steps:
      - name: Review with jim
        uses: acarmisc/the-office-ai-squad@v0.1.0
        with:
          agent: jim
          post: ${{ vars.SQUAD_POST == 'true' && 'true' || 'false' }}
          llm-base-url: ${{ vars.LLM_BASE_URL }}
          llm-api-key: ${{ secrets.LLM_API_KEY }}
```

The action is a composite action (`action.yml` at the repository root). It does not check out the repository and does
not run code from the pull request. The job workspace holds only what the workflow puts there.

### Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `agent` | `jim` | `jim`, `angela`, `dwight`, `darryl` or `michael`. |
| `post` | `false` | `"true"` publishes the review (inline comments, one summary, the `ai-review/<agent>` status). Anything else is a dry run. |
| `skills-path` | empty | Directory of `*/SKILL.md`, relative to the workspace, injected as payload skills. See [skills](#how-project-skills-work). |
| `model` | empty | A model alias from the organisation's allow-list. Empty uses the configured model. |
| `fail-on` | `none` | `none`, `request_changes` or `incomplete`. See [gating merges](#gating-merges). |
| `github-token` | the job token | The token that reads the pull request and writes the review. |
| `llm-base-url` | required | The gateway URL. Store it in a repository variable. |
| `llm-api-key` | required | The gateway key. Store it in a secret. |
| `image` | `ghcr.io/acarmisc/code-squad:0.1.0` | The image to run. Pin a release tag or a digest. |

### Outputs

| Output | Value |
| --- | --- |
| `verdict` | `approve`, `comment`, `request_changes`, `incomplete`, or `none` when no review ran |
| `status` | `complete`, `incomplete`, `failed`, or `none` |
| `findings` | The number of findings in the result |
| `result-file` | The path of the full JSON result on the runner (empty when no review ran). Upload it as an artifact if you need the whole result. |

### What the job does

```mermaid
sequenceDiagram
    autonumber
    participant PR as Pull request event
    participant Job as Runner job (workflow)
    participant Box as Container (squad ci review)
    participant API as GitHub API
    participant LLM as LLM gateway
    PR->>Job: pull_request (opened, synchronize, reopened, ready_for_review)
    Job->>Job: skip the job when the pull request is a draft
    Job->>Box: docker run, env by name, event file and workspace read only
    Box->>Box: read GITHUB_EVENT_PATH; skip drafts and forks without a key
    Box->>API: pull request, diff, files; base-branch .agents/skills and .squad/config.yml
    Box->>LLM: review (the agent's tools, untrusted content wrapped)
    alt post is true
        Box->>API: inline comments, one summary, ai-review/agent status
    else dry run
        Box-->>Box: publication refused; findings only in the result
    end
    Box-->>Job: squad-result.json in RUNNER_TEMP, exit code from fail-on
    Job->>Job: summary and outputs written to the step summary
```

The container runs as the job's user with a read-only root filesystem. Secrets are passed by environment variable name
(`-e LLM_API_KEY`), never as command-line arguments. The result is written to `RUNNER_TEMP`, outside the workspace.

### Skipped reviews

| Situation | What happens | Exit code |
| --- | --- | --- |
| Draft pull request | Skipped with a message in the log | 0 |
| Fork pull request without `LLM_API_KEY` | Skipped: forks get no secrets | 0 |
| Event is not a pull request (`push`, `pull_request_review`, ...) | Refused | 2 |
| Missing `GITHUB_TOKEN`, `LLM_BASE_URL` or `LLM_API_KEY` | Refused with the missing name | 2 |
| Agent not available in CI (`pam`) | Refused | 2 |
| `skills-path` outside the workspace, or not a directory | Refused | 2 |
| Model call fails, or the run fails | Result with `status: failed` | 1 |

A skipped review writes no result file, and the step summary says so.

## How project skills work

Project conventions reach the agent in three ways. They stack in precedence order.

1. **Repository skills from the base branch.** Skills in `.agents/skills/<name>/SKILL.md` are read from the pull
   request's base branch through the provider, as in the deployed service. The pull request cannot change them before
   they are merged. Write conventions there, as described in [skills authoring](../onboarding/skills-authoring.md).
2. **Shared skills from the workspace (`skills-path`).** The action reads every `*/SKILL.md` under the directory you
   name, and sends them as payload skills. Payload skills take precedence over repository skills with the same name.
   Use this for conventions that several repositories share. Check out a shared skills repository at a pinned ref
   (the example does this, with `actions/checkout` pinned to a SHA):

   ```yaml
   - name: Check out the shared review skills
     uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
     with:
       repository: acme/review-skills
       ref: <a reviewed commit>
       path: .squad-shared-skills
       persist-credentials: false
   ```

   Then set `skills-path: .squad-shared-skills`. Point it at a trusted shared checkout or at the base branch, never at
   the pull request head: a skill read from the head is written by the author of the change under review.
   The skill limits of the organisation apply. The run prints which skills it injected, and the result lists the skills
   the agent loaded in `stats.skills_applied`.
3. **Organisation and repository configuration.** `.squad/config.yml` in the repository is read from the base branch.
   Create a starting file with `squad config init react --output .squad/config.yml` (or `java`, `generic`) and commit
   it. Every review then uses its rules and limits. The organisation file, when one is mounted at `SQUAD_CONFIG_FILE`, sets the defaults.

## Outputs and the step summary

The step summary shows the verdict, status, number of findings and tokens, a table of the top findings (blockers first,
at most 20) with severity, file and line, and the warnings. The full result is in the `result-file`. The job log
shows the same report from the container.

Use the outputs to act on the review in later steps:

```yaml
      - name: Review with jim
        id: review
        uses: acarmisc/the-office-ai-squad@v0.1.0
        with:
          llm-base-url: ${{ vars.LLM_BASE_URL }}
          llm-api-key: ${{ secrets.LLM_API_KEY }}

      - name: Report the verdict
        if: always()
        run: echo "verdict=${{ steps.review.outputs.verdict }} findings=${{ steps.review.outputs.findings }}"
```

Do not interpolate outputs into `run:` scripts from untrusted fields. The values here are enumerations and a count, and
the summary sanitises the text it writes.

## Gating merges

`fail-on` controls the exit code of the step. The result is always written before the exit.

| Value | The step fails when |
| --- | --- |
| `none` (default) | The run failed. A review with findings passes. |
| `request_changes` | Also when the verdict is `request_changes`. |
| `incomplete` | Also when the run is incomplete or the verdict is `incomplete`. |

Start with `none`. The review is advisory until the team has seen enough reviews to trust the verdict. Then add the
check as a required status only if the team agrees that a `request_changes` verdict should block a merge. The squad never
merges, and a review with `fail-on: none` never blocks anything.

## GitHub Enterprise Server

Set nothing special. The runner sets `GITHUB_API_URL` to the enterprise API (`https://ghes.example.com/api/v3`), and the
job passes it to the squad, which reads the pull request and writes the review there. The image must be able to reach
that host and the LLM gateway. The advisory sources that `dwight` uses (`api.github.com`) need outbound access or must
be switched off, as described in `examples/github/ghes-notes.md` in the repository.

## Security notes

- **Use `pull_request`.** Forks get read-only tokens and no secrets, so the skip rule holds. `pull_request_target` runs
  with the base repository's secrets for fork pull requests. The squad does not run fork code, but a workflow on that
  event gives the pull request access to the gateway key. The action accepts the event, and the example does not use it.
- **No checkout of the pull request.** Do not add `actions/checkout` of `github.event.pull_request.head.sha` to the job.
  The review reads the change through the API.
- **Keys stay in the environment.** `llm-api-key` and `github-token` appear only in `env:` blocks of the action, and reach
  the container by name.
- **Least privilege.** The example's permissions are the minimum the job needs. Do not grant `contents: write`.
- **Untrusted text.** Diffs, comments, issues and skills are wrapped as untrusted content before the model reads them,
  as in the service. See [prompt injection](../security/prompt-injection.md).

## Troubleshooting

The table lists the symptoms in the job log and in the step summary. More are in
[troubleshooting](../getting-started/troubleshooting.md#github-actions-review).

| Symptom | Likely cause and fix |
| --- | --- |
| The job is green and the summary says no review ran | A draft pull request, or a fork without secrets. Both are skipped on purpose. |
| `event ... is not a pull request event` (exit 2) | The workflow runs on something other than `pull_request`. Use the example's trigger. |
| `pull_request_review` or `pull_request_target` refused | Only `pull_request` is supported in the example; see the security notes. |
| `GITHUB_TOKEN is not set` (exit 2) | The `github-token` input is empty, or the workflow overrides it with an empty value. |
| `LLM_BASE_URL and LLM_API_KEY must be set` (exit 2) | The repository variable or the secret is missing on a pull request from the same repository. A Dependabot pull request has no repository secrets unless they are granted to Dependabot. |
| `403` when posting, or the status is missing | The workflow's permissions lack `pull-requests: write` or `statuses: write`, or an organisation policy lowered the default `GITHUB_TOKEN`. |
| `401` from the gateway, `status: failed` | The gateway key is wrong or expired. Rotate the secret. |
| `denied` or `unauthorized` when pulling the image | The package is private. Make it public, or log in on the runner with a token that can read packages. |
| `skills path ... is not a directory` (exit 2) | The checkout of the shared skills did not run, or `skills-path` names the wrong directory. |
| Findings appear with no skill applied | The skill is not in the base branch, or its `applies_to` does not match the changed files. The run lists skipped skills under `warnings`. |

## Limits of this mode

- One agent per step. Add a second step with a different `agent` to run another reviewer. Each step is a separate run.
- No webhooks, no metrics, and no state shared between runs.
- `pam` is not available in CI. `michael` runs in the job and calls its specialists in the same process. The
  per-specialist timeouts still apply, but a specialist that overruns keeps running until the job ends, and the circuit
  breakers of the HTTP client do not apply.
- Configuration and skills come from the base branch on every run. A change to `.squad/config.yml` or to a skill in the
  pull request applies only after it is merged.

## See also

- [GitHub](github.md): the provider, the App and the deployed webhook.
- [New project checklist](../onboarding/new-project.md): the steps shared by both modes.
- [Skills authoring](../onboarding/skills-authoring.md) and [configuration concepts](../configuration/concepts.md).
- [Decision 0014](../decisions/0014-github-actions-review.md): why the mode runs in the job, and what it leaves out.
