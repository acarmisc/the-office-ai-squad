# Troubleshooting

Find the symptom in the left column, then check the cause and the fix. Messages in quotes are the text the squad or the chart prints,
so you can search for them in logs and in the result's `warnings`. For the operational view (dashboards, alerts, incidents), see the
[runbook](../operations/runbook.md).

## HTTP and API

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `401` on `POST /invocations` or `GET /jobs/{id}`, body `missing or invalid bearer token` | No `Authorization` header, a different token, or the pod started before the Secret was updated | Send `-H "Authorization: Bearer $SQUAD_API_TOKEN"`. The token is read at start-up: after you rotate `api-token`, restart the agent pods (`kubectl rollout restart`). |
| `401` with `SQUAD_API_TOKEN is not set` in the logs | `api.tokenSecret.name` is empty and `api.allowUnauthenticated` is false, so every request is refused | Create the Secret and set `api.tokenSecret`. For a local demo only, set `SQUAD_ALLOW_UNAUTHENTICATED=1`. |
| `413` with `request body is too large` | The request is over `SQUAD_MAX_REQUEST_BYTES` (default 1,000,000 bytes) or `limits.max_request_bytes` | Send less text. Split a large change request into several runs, or raise the limit deliberately. Webhook bodies have their own limit, `SQUAD_MAX_WEBHOOK_BYTES`, checked before the signature. |
| `422` with `model '<name>' is not in the organisation's allow-list` | The request names a model that `llm.allowed_models` does not contain | Use an allowed alias, or add the alias to `llm.allowed_models` in the organisation file. |
| `422` with a message that a field is organisation-only (for example `... is organisation-only`) | A call or repository file set a key only the organisation may set | Move the setting to the organisation file, or remove it from the request. |
| `409` with `{"status": "in_flight"}` | The same `Idempotency-Key` (or body key) is still running | Wait and repeat the call; it returns the stored result when the first run finishes. Use a new key for a new run. |
| `503` with `agent is not loaded` (or `/ready` returns `not_ready`) | The agent specification or the organisation file failed to load; `/ready` names the exception type | Run `squad config validate` on the mounted files, then check the agent's logs for `agent failed to load`. |

## Results

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `status: incomplete` and `verdict: incomplete` | A specialist failed, timed out, or the run ended before `finish` (iteration or budget limit) | Read the `warnings` and the summary. `incomplete: jim failed` names the specialist; `iteration limit reached before finish()` means the change is too large or the turn limit is too low. Split the change, or raise `agents.<id>.max_iterations` within `limits.max_iterations`. |
| `status: failed` | The run raised, most often the model gateway | Read the warning (it names the exception type). Check gateway health and the NetworkPolicy allow-list, then rerun in dry run. |
| Verdict is `request_changes` but the findings look minor | A blocker or, in the high-risk tier, a major finding | Check `data.risk` and the blocker findings. See the [FAQ](../faq.md). |
| No comments appear | The request was a dry run (`post: false`), or `posting.force_dry_run` is `true` | Expected in dry run. The warning `dry-run blocked N external write attempt(s)` confirms it. Set `force_dry_run: false` only at go-live. |
| Comments appear twice | A marker was removed (an edited comment), or two squads publish to one change request | Keep each comment's `<!-- code-squad:<id> -->` marker. Check that only one publisher is active and that `routing.specialists_post` is false. Rerunning a review does not duplicate marked comments. |
| A finding is missing from the inline comments | It is on a line the change did not add, so it is posted as a general note | Look in the summary's notes. This is by design; see [review sequence](../architecture/review-sequence.md). |
| `Configuration notes` in the summary, or a warning about a rejected layer | A repository file breaks a tighten-only or organisation-only rule, so the whole file is ignored | Run `uv run squad config explain <project> --repo-config .squad/config.yml` and fix the key it names. |

## VCS

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| VCS `401` (warning or `squad_vcs_errors_total`) | The token is wrong, expired or revoked, or the GitHub App key is not the one for that App | Check the Secret named by `auth.token_secret` or `auth.private_key_secret`. Rotate it as in [Secrets](../deployment/secrets.md#rotation). |
| VCS `403` | The token lacks a scope: GitLab needs `api` and `read_repository`; a GitHub App needs read on contents, pull requests and metadata | Add the scope, or the App permission, and reinstall the App on the repository. See [GitLab](../vcs/gitlab.md#the-bot-identity) and [GitHub](../vcs/github.md#create-the-app). |
| VCS `404` | Wrong `match` path or `base_url`, or the bot cannot see the project | Use the exact `group/repo` or `owner/repo` path. For self-managed hosts, set `base_url` to the API root. A 404 is not counted in the error metric, so check the logs. |
| The webhook is ignored (`202` with a `reason`) | `vcs.bot_username` is missing or wrong, the change request is a draft, has a skip label or a WIP title, or the commenter is not allowed | Read the `reason` in the response body and fix that cause. See [GitLab](../vcs/gitlab.md) and [GitHub](../vcs/github.md) for the trigger rules. |

## Webhooks

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `404` on `/webhooks/<provider>` | The provider is disabled, so `WEBHOOK_PROVIDERS` on michael does not name it and no route exists | Set `webhooks.<provider>.enabled: true`. The chart also exposes the path through the ingress. |
| `401` on a webhook delivery | The signing secret does not match the secret stored in the cluster | Re-enter the secret in the VCS webhook settings and in `gitlab-webhook-secret` or `github-webhook-secret`. Check for trailing whitespace. |
| `503` on a webhook | The organisation file is invalid | Validate the mounted `squad.yaml`, fix it and redeliver the event. |
| Response body `{"status": "duplicate"}` | The delivery id was already seen | Expected. Use a new delivery id when you replay on purpose. |

## Chart and cluster

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `helm` fails with `michael keeps webhook and run state in process: set sessionStore.url` | More than one michael replica, or an HPA, without a shared session store | Set `sessionStore.url` to a Redis URL, or keep `michael` at one replica. |
| `helm install` prints `WARNING: llm.baseUrl is empty` and model calls fail | `llm.baseUrl` was not set | Set `llm.baseUrl` in the values file and upgrade. |
| Pods run but the agent logs `SQUAD_API_TOKEN is not set` | Expected when `api.tokenSecret` is empty | Set the token Secret (step 2 of [Deploy to Kubernetes](deploy-to-kubernetes.md#step-2-secrets)). |
| A NetworkPolicy blocks the gateway or the VCS | The CIDR list does not include the destination | Add the destination's IP range to `llmGatewayCIDRs` or `vcsCIDRs`, or route through `egressProxy`. Hostnames are not allowed. |
| The `ConfigMap` changes are not picked up | Changes are hot-reloaded on the next request; with `config.restartOnChange` the pods roll | Wait for the next request, or check `squad_config_reload_failures_total` when a reload is rejected. |

## pam and the sandbox

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| pam refuses to start with `pam requires the Kubernetes sandbox; set ALLOW_LOCAL_SANDBOX=1` | The sandbox is off (`sandbox.enabled: false`) and no sandbox namespace is set | Enable the sandbox and create the labelled namespace. `ALLOW_LOCAL_SANDBOX=1` is for a disposable test cluster only, as in the kind example. |
| Sandbox pod stuck in `Pending` or `ContainerCreating` | Image pull failure, quota, or a Pod Security rejection | `kubectl -n code-squad-sandbox describe pod <name>`. Check the image name, the pull secret and the namespace label `pod-security.kubernetes.io/enforce=restricted`. |
| pam halts with `incomplete` and `loop detected` | The same failing command ran three times | Read the first error line in the result, and fix the repository or the task. |
| The chart does not create the sandbox namespace | Expected: the namespace is created by the platform team | Run the two commands in step 1 of [Deploy to Kubernetes](deploy-to-kubernetes.md#step-1-namespaces). |

## Gateway

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `429` or `5xx` from the gateway | Too many concurrent reviews, or the upstream is overloaded | The squad retries once with `fallback_model` when one is set. Lower `routing.fan_out_concurrency`, raise `trigger.debounce_seconds`, or ask the gateway team for a higher limit. |
| Invocations fail with a connection error | The gateway URL is wrong, or the NetworkPolicy blocks it | Check `llm.baseUrl` and `llmGatewayCIDRs`. The result names the exception type in `warnings`. |
| Model requests succeed but the names are unknown | The gateway does not serve `haiku-5-5` or `sonnet-5-5` | Map those names in the gateway (see step 3 of [Deploy to Kubernetes](deploy-to-kubernetes.md#step-3-the-llm-gateway)). |

## GitHub Actions review

The in-runner mode runs in the job; see [GitHub Actions review](../vcs/github-actions.md) for the setup.

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The step is green and the summary says no review ran | A draft pull request, or a fork pull request without `LLM_API_KEY` | Both are skipped on purpose. Mark the draft ready, or review the fork change by hand. |
| `error: ... is not a pull request event` (exit 2) | The workflow is not triggered by `pull_request` | Use the trigger in `examples/github/github-actions-review-jim.yml`. |
| `error: GITHUB_TOKEN is not set` (exit 2) | The `github-token` input is empty | Leave it at its default (`${{ github.token }}`). |
| `error: LLM_BASE_URL and LLM_API_KEY must be set` (exit 2) | The variable or the secret is missing for a pull request from the same repository | Add `LLM_BASE_URL` as a repository variable and `LLM_API_KEY` as a secret. Dependabot runs need the secret granted to Dependabot. |
| `403` when posting, or no `ai-review/<agent>` status | The job lacks `pull-requests: write` or `statuses: write` | Set the permissions in the workflow. An organisation policy can lower the default token. |
| `status: failed` with `model call failed` | The gateway rejected the call (`401`) or is unreachable | Check the key and `LLM_BASE_URL`. Rotate the secret if the key is wrong. |
| `error: --skills-path ... is not a directory` (exit 2) | The shared-skills checkout did not run, or the path is wrong | Check the `actions/checkout` step and the `path` it writes to. |
| The image cannot be pulled | The package is private to the runner | Make the package public, or pass a pull credential to the job. |

## Still stuck

1. Collect the `invocation_id` from the logs, the `stats.config_hash` from the result, and the exact `warnings`.
2. Run `uv run squad config explain <project>` against the same files to see which layer set each key.
3. Open an issue with the [bug report template](https://github.com/acarmisc/the-office-ai-squad/issues/new?template=bug_report.yml).
   Do not paste tokens, prompts or diffs from private repositories.
