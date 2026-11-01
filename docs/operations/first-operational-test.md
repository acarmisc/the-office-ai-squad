# First operational test

This page runs the squad on one real project for the first time. It is a trial with a fixed scope, a dry-run phase and a
posting phase, and it has a rollback switch. Read [ADR 0013](../decisions/0013-operational-readiness.md) first: it lists
the defects that were fixed before this test and the items that are deferred until the test has produced evidence.

## Goal and scope

- **Goal.** Show, on one real change request stream, that the verdicts, findings and summaries are correct and useful, that
  the cost and latency are acceptable, and that posting is safe. Record every result in the table at the end.
- **Project.** One real GitLab or GitHub project, chosen by the platform team. Not a production-critical service.
- **Agents.** `michael` (orchestrator) with `jim` (React), `angela` (Java), `dwight` (security) and `darryl` (DevOps,
  review only). Each agent that matches the project's stack runs; the others return nothing.
- **Off.** `pam` (implementer), webhooks (`webhooks.gitlab.enabled` and `webhooks.github.enabled` stay `false`), the
  ingress, `routing.specialists_post` (specialists return findings to michael), and formal approvals (`vcs.approve_mode:
  none`).
- **Reviews are started by hand**, with `scripts/trial_review.sh`. Nothing starts when a merge request is opened or pushed.
- **Status.** The commit status `ai-review/michael` is informational. It must not be a required status in the project's branch
  protection.

## Prerequisites

- **LLM gateway.** A LiteLLM endpoint that serves the aliases `haiku-5-5` and `sonnet-5-5`, its base URL (for example
  `https://llm-gateway.example.internal/v1`), and a gateway key. Only the key goes into a Secret.
- **A bot identity** with the smallest scopes that work:
  - GitLab: a project access token for a dedicated bot, role Developer, scopes `api` and `read_repository`. Do not add
    `write_repository`, because pam is off. See [GitLab](../vcs/gitlab.md#the-bot-identity) and
    `examples/gitlab/token-scopes.md` in the repository.
  - GitHub: a GitHub App installed on the trial repository only, with the permissions in
    [GitHub](../vcs/github.md#create-the-app). Set Contents to read, because pam is off. Keep the App's bot login,
    `<app slug>[bot]`, for `vcs.bot_username`.
- **A runtime.** A Kubernetes cluster where the chart can be installed, with a CNI that enforces NetworkPolicy (otherwise the
  policies are accepted and not enforced), or a Docker host for a local dry run with the Compose files in
  [Local environments](../deployment/local.md). The procedure below assumes Kubernetes.
- **Tools.** `helm` 3, `kubectl`, `curl`, `python3` and this repository checked out at the release you tested.
- **Real values.** Replace every RFC 5737 address in
  `deploy/helm/code-squad/values-examples/operational-test.yaml`, the project's path, the bot login and the secret names.

## Step by step

### 1. Create the Secrets

The chart reads two Secrets. Create them outside the repository, and never commit their values.

```bash
kubectl create namespace code-squad
kubectl -n code-squad create secret generic code-squad-secrets \
  --from-literal=llm-api-key="$LLM_KEY" \
  --from-literal=gitlab-token="$GITLAB_BOT_TOKEN"
kubectl -n code-squad create secret generic code-squad-api \
  --from-literal=api-token="$(openssl rand -hex 32)"
```

For GitHub, replace `gitlab-token` with `github-app-private-key` (the PEM text) and use the App's `private_key_secret`
name. Keep the API token: `trial_review.sh` sends it.

### 2. Set the organisation config and the project registry

Edit `config.org` and `config.projects` in the values file:

- `config.org.posting.force_dry_run` stays `true`. This is the switch between dry run and posting.
- `config.org.vcs.bot_username` is required. GitLab: `project_<id>_bot`. GitHub: `<app slug>[bot]`. Without it the
  squad ignores every event for the project.
- `config.projects.projects[0]` names the real project: `match`, `key`, `provider`, `base_url` (GitLab) and
  `auth.token_secret`. The GitHub variant is in the comments of the values file.
- `config.org.llm.allowed_models` lists the two aliases. Any other model is refused with `422`.

The org file is hot-reloaded: the next invocation reads it again, without a restart.

### 3. Install the chart

```bash
helm upgrade --install code-squad deploy/helm/code-squad \
  --namespace code-squad \
  -f deploy/helm/code-squad/values-examples/operational-test.yaml \
  --set image.repository=registry.example.com/platform/code-squad \
  --set image.tag=0.1.0
```

`helm lint` and `kubeconform` pass for this file in CI (`just helm-lint`), and `tests/test_values_examples_config.py`
checks its organisation and registry blocks against the schema.

### 4. Verify readiness

Expose each agent that is deployed on its own local port, then check readiness:

```bash
kubectl -n code-squad port-forward svc/code-squad-michael 8080:8080 >/dev/null &
kubectl -n code-squad port-forward svc/code-squad-jim 8081:8080 >/dev/null &
kubectl -n code-squad port-forward svc/code-squad-angela 8082:8080 >/dev/null &
kubectl -n code-squad port-forward svc/code-squad-dwight 8083:8080 >/dev/null &
kubectl -n code-squad port-forward svc/code-squad-darryl 8084:8080 >/dev/null &
for port in 8080 8081 8082 8083 8084; do curl -sS "localhost:${port}/ready"; echo; done
```

Each `/ready` answers `{"status": "ready", "agent": ...}`. `/ready` does not call the gateway, so also run one dry-run
review (step 6) before you trust the setup. Check that `pam` has no Deployment, and that no `/webhooks` route exists
(`curl -sS -o /dev/null -w '%{http_code}' -X POST localhost:8080/webhooks/gitlab` must return `404`).

### 5. Choose the change request

Pick a small change request with three features, so one review exercises the anchoring rules:

- a **context-line edit**: a finding on a line the change did not add (the squad must post it as a general note, not an
  inline comment);
- a **rename**: a file moved and edited in the same change (its path must be normalised and anchored to the new path);
- a **multi-line change**: a finding over several added lines (it must be anchored to the added range).

Write the change request number and the project path down. Use the same change request for the first dry run and the
first post.

### 6. Dry run

```bash
export SQUAD_API_TOKEN="$(kubectl -n code-squad get secret code-squad-api -o jsonpath='{.data.api-token}' | base64 -d)"
scripts/trial_review.sh http://localhost:8080 platform/example-app 123
```

The script sends `post: false`, prints the warning that nothing is written to the VCS, and then prints one report:
`status`, `verdict`, finding counts by severity, `posted` counts (all must be `0`), the warnings, the token counts
(`input` and `output`), the number of turns, the tool calls and the wall time measured by the script. The exit code is `1`
on an HTTP error or a failed run. Copy the printed report into the results table at the end of this page.

For each finding, check the file, the line range and whether the rationale is correct. For each warning, check whether it
is expected. In particular a truncated or binary file must appear under "not reviewed", and a truncated text file caps the
verdict at `comment`.

### 7. Repeat on three to five change requests

Run step 6 on three to five more change requests, including at least one with no findings and one with a dependency
change (for `dwight`). For each run, write down the cost and latency in the results table below. A run that returns
`incomplete` is a result too: record the warning that explains it.

### 8. Switch to posting

Only after the acceptance criteria for the dry run are met:

1. Set `config.org.posting.force_dry_run: false` in the values file and run `helm upgrade` again with the same command as step 3.
   The org file is mounted from a ConfigMap, so the new file reaches the pods within a minute or two, and the next invocation
   reads it. No restart is needed. Confirm it: `scripts/trial_review.sh` without `--post` must no longer print the
   `force_dry_run` warning in the report.
2. Confirm that `ai-review/michael` is not a required status in the project's branch protection.
3. Run the same change request once with posting:

   ```bash
   scripts/trial_review.sh http://localhost:8080 platform/example-app 123 --post
   ```

   The script prints a warning before it starts. Check on the change request:
   - each inline comment sits on an added line, and the multi-line finding covers its range;
   - the context-line finding is in the summary, under "General notes", and not as an inline comment;
   - the summary comment carries the marker `<!-- code-squad:summary:michael -->`, and the "Configuration notes" section
     appears when the report has any;
   - the commit status `ai-review/michael` has the verdict's state.
4. Run the same change request again with `--post`. Expect no new inline comments and one summary that is updated in
   place. Duplicates are a failure: the markers must match comments that the bot wrote.
5. Check the bot identity filter. The bot's own comments must not start a review, and for GitHub the App's `[bot]` login must
   equal `vcs.bot_username` exactly (the comparison ignores case). Compare the author of the comments with the value in the
   org file.

### 9. Record the provider responses as conformance fixtures

The GitLab and GitHub providers are tested against recorded responses in `tests/vcs/fixtures/<provider>/`, replayed through
respx. The responses from this test (context lines, a renamed file, a multi-line range, the GitHub App identity) are the
evidence that the squad behaves the same way on a live host. Record them like this:

1. On a workstation that has the bot token (never on a shared host), run the provider against the change request with an
   httpx event hook that writes each response body to a file. Do not write headers, because they carry tokens.
2. Replace every real identifier with the fake ones used by `tests/vcs/recorded.py` (project `acme/web`, the fake users and
   commit ids). Search the files for the real host name, the project name, the bot login and anything that looks like a
   token before you copy them. `scripts/secret_scan.py` must pass.
3. Copy the files into `tests/vcs/fixtures/gitlab/` or `tests/vcs/fixtures/github/`, add the route to
   `tests/vcs/recorded.py`, and add a test in `tests/vcs/test_gitlab.py` or `tests/vcs/test_github.py` that asserts the
   anchoring result. Run `just test tests/vcs`.

### Rollback

- **Stop posting, keep the service.** Set `config.org.posting.force_dry_run: true`, run `helm upgrade`, and wait for the new
  file. From the next invocation on, no run writes to the VCS, and any run that is already running finishes with its original
  settings.
- **Stop the service.** `kubectl -n code-squad scale deploy/code-squad-michael --replicas=0`. Nothing is started by webhooks,
  because they are off.
- **Remove the status.** If the commit status is stuck on a change request, set it to success by hand in the VCS, or re-run
  the review with a fixed verdict. The squad never merges and never approves in this test.

## Acceptance criteria

Each criterion needs a date, a change request and the name of the person who checked it.

| # | Criterion | Result |
| --- | --- | --- |
| A1 | Every deployed agent reports `/ready`, and `pam` and the webhook routes are absent. | |
| A2 | Every dry run has `posted` counts of zero and no status write. | |
| A3 | The context-line finding is a general note, not an inline comment. | |
| A4 | The renamed file is anchored under its new path, or it is a general note with a reason. | |
| A5 | The multi-line finding is one inline comment over its added range. | |
| A6 | A truncated or binary file is listed under "not reviewed". A truncated text file caps approve at comment. | |
| A7 | A failed specialist makes the verdict `incomplete` (or `request_changes` when a blocker exists) with a warning. | |
| A8 | No run exceeds `limits.max_run_tokens`, and every run's tokens and wall time are recorded. | |
| A9 | Re-running a posted change request adds no duplicate inline comments and updates the summary in place. | |
| A10 | The bot's own comments do not start a run, and `vcs.bot_username` matches the bot login exactly. | |
| A11 | The `force_dry_run` switch stops posting on the next invocation, without a restart. | |
| A12 | Rollback was tested on the cluster (step 8 reversed). | |
| A13 | The provider responses for A3 to A5 are recorded as fixtures and the tests pass. | |

## Results

Copy this table for every run. Fill in the cost from the gateway's tags (`agent:<id>`, `project:<project>`), not from the
result alone, because `stats.cost_hint` is never set.

| Date | Change request | Mode | Agent | Status | Verdict | Findings (B/M/m/n) | Input / output tokens | Wall time (s) | Warnings of note | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | dry run | michael | | | | | | | |

## Known risks

- **Duplicate runs across replicas.** With one michael replica this does not happen. With more, webhook de-duplication is per
  replica, and the in-flight claim needs Redis. This test runs one replica.
- **In-memory state.** The job store and the claim are in memory unless `sessionStore.url` is set, and the in-process
  store holds 10,000 entries. A replica restart loses running jobs; re-run the change request.
- **Model judgement.** The model can miss a defect or invent one. Read every finding before you trust it, and record the
  misses. The deterministic rules limit the effect of a bad finding; they do not check its correctness.
- **Shared Secret.** Every agent pod mounts the whole Secret, so a compromised agent can read the VCS token and the gateway key.
  Keep the bot token narrow and rotate it after the test.
- **Network policies.** The example CIDRs are placeholders. An install without an enforcing CNI accepts the policies and enforces
  nothing.
- **No live model evaluation yet.** The offline replay tests measure the pipeline, not the model. This test is the first
  live measurement.
- **Advisory data.** dwight marks advisory data it cannot reach as unverified, and withholds approve. Without egress to the
  advisory hosts, dwight's verdicts on dependency changes are capped.
