# GitHub

Code Squad works with github.com and GitHub Enterprise Server (GHES). It reads pull requests, diffs,
files, workflow runs and job logs through the REST API, and writes reviews, comments, commit statuses,
check runs (with a GitHub App) and, for `pam`, branches and pull requests. The same provider serves both
hosts; only the API base URL changes. For GHES specifics see
`examples/github/ghes-notes.md` in the repository.

## Authentication

Two options. A **GitHub App** is preferred: each installation token is scoped to the repositories where the
App is installed, expires after an hour, and is refreshed by the squad. A **personal access token** is the
fallback, and it has no check runs.

| Setting | Where | Notes |
| --- | --- | --- |
| App id | `vcs.auth.app_id` (number) | Organisation file or registry. Not a secret. |
| Installation id | `vcs.auth.installation_id` (optional) | When omitted, the installation is looked up for each repository. |
| Private key | `vcs.auth.private_key_secret` (secret name, for example `github-app-key`) | PEM text in the secret store. |
| Token | `vcs.auth.token_secret` (secret name) | For the token fallback. |

Keep the private key and tokens out of configuration files: only their secret names appear there.

## Create the App

Use the manifest in `examples/github/github-app-manifest.json` as the starting point. Replace the host
names, then register the App from the manifest flow on the organisation.

The App needs these permissions. The manifest lists the same set.

| Permission | Level | Used for |
| --- | --- | --- |
| Metadata | read | Required by GitHub; identity and repository lookup. |
| Contents | read | Reading files, trees, the base branch and skill files. |
| Contents | write | Pushing the branch of `pam`. Lower it to read when `pam` is not deployed. |
| Pull requests | write | Reviews, inline comments, creating pull requests. |
| Issues | write | Summary comments and issue comments. |
| Checks | write | Check runs for verdicts. |
| Commit statuses | write | Commit statuses `ai-review/<agent>`, used when check runs are not available. |
| Actions | read | Workflow runs and job logs for darryl. |

Subscribe to these events: `pull_request`, `issue_comment`, `pull_request_review_comment` and `issues`
(`issues` only when `pam` picks up assigned issues).

Install the App on the repositories that the squad should review. An App installed on all repositories
covers future ones, which may be more than intended; prefer selected repositories.

The bot identity for a GitHub App is `<app slug>[bot]`. Set `vcs.bot_username` to that value, for example
`code-squad-review[bot]`.

## Personal access token fallback

Use a fine-grained token scoped to the reviewed repositories. Grant:

| Permission | Level |
| --- | --- |
| Metadata | read |
| Contents | read (write only for `pam`) |
| Pull requests | write |
| Issues | write |
| Commit statuses | write |
| Actions | read (only for darryl) |

A classic token needs the `repo` scope, which is broader than the fine-grained set. Prefer the App.

With a token there are no check runs. Verdicts use commit statuses, and michael adds the warning
"check runs unavailable; used commit status" to the result. The bot identity is the token owner's login.

## Webhook

On the App (or the repository), set:

| Field | Value |
| --- | --- |
| Payload URL | `https://<squad host>/webhooks/github` |
| Content type | `application/json` |
| Secret | the value stored as `github-webhook-secret` |
| SSL verification | enabled |
| Events | as listed above |

Enable the route on michael with `WEBHOOK_PROVIDERS=github`. The chart does not set it; see
[Ingress and webhooks](../deployment/ingress-webhooks.md).

Deliveries are verified with `X-Hub-Signature-256`, an HMAC-SHA256 of the raw body with the secret, compared
in constant time. A delivery id that already reached a final outcome returns `200` with `duplicate`; a delivery that failed
before an outcome can be redelivered.

## CI and workflow snippets

`examples/github/github-actions-workflow.yml` runs on `pull_request` with `permissions: contents: read`. It
calls michael with `curl` and `jq` only, so no third-party action runs with the job token. The `SQUAD_POST`
repository variable turns publication on; the default is a dry run. Fork pull requests get no secrets, and
the workflow reads only variables.

## Verdicts and approvals

| Signal | When |
| --- | --- |
| Check run `ai-review/<agent>` | App authentication. Conclusion `success` or `failure`; pending verdicts are reported as an in-progress check. |
| Commit status `ai-review/<agent>` | Token authentication, or when check runs are not available. |
| Review `COMMENT`, `REQUEST_CHANGES` or `APPROVE` | Only when `vcs.approve_mode` allows it. `APPROVE` is submitted only for an approve verdict. |

`vcs.approve_mode` defaults to `none`. The squad never merges.

## Capabilities on GitHub

| Capability | App | Token |
| --- | --- | --- |
| Check runs | Yes | No |
| Commit statuses | Yes | Yes |
| Batched review (inline comments in one review) | Yes | Yes |
| Formal approval | Yes, when allowed | Yes, when allowed |
| Draft pull requests | Yes | Yes |
| Resolve threads | No (needs GraphQL, not implemented) | No |
| Job logs | Yes | Yes |
| Issues | Yes | Yes |
| Push (HTTPS, for `pam`) | Yes | Yes |

The full matrix is in the [capability reference](../reference/vcs-capabilities.md).

## GitHub Enterprise Server

Set the provider to `github` and the API base URL to the host's `/api/v3` path, in the registry entry. The
webhook, the App and the permissions are the same. Advisory data for dwight comes from `api.github.com`, which
is public, so a GHES deployment without outbound access must disable the GitHub advisory source or route it
through the egress proxy. The clone host for `pam` follows the API host. Details are in `examples/github/ghes-notes.md`.

## Rate limits and retries

The client honours primary and secondary limits. A `403` with rate-limit headers and a `429` are waited out
with the reset or `Retry-After` time when present, otherwise with exponential back-off capped at 30 seconds.
A single wait is at most 120 seconds, requests time out after 30 seconds, and list calls follow up to 100
pages. A limit that persists is an error for the operation, reported as a warning.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| `401` on webhook | Secret mismatch. Re-enter `github-webhook-secret` exactly. |
| No check run, only a warning about commit status | The token fallback is in use, or the App lacks `checks: write`. |
| `403` from the API on writes | A permission is missing on the App, or the App is not installed on the repository. |
| `404` on the App installation lookup | The App is not installed on that repository. Install it, or set `installation_id`. |
| Provider cannot be inferred | Use `provider: github` in the registry entry for a GHES host. |
| `pam` cannot push | Contents write is missing, or the branch is protected. |
| Resolve-thread warning | Expected on GitHub. Threads are not resolved by the squad in this version. |
