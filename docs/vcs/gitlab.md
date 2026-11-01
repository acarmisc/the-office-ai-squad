# GitLab

Code Squad works with GitLab SaaS (`gitlab.com`) and self-managed GitLab. It reads merge requests,
diffs, files, pipelines and job logs through the REST v4 API, and writes discussions, notes, commit
statuses and, for `pam`, branches and merge requests. Both `gitlab.com` and self-managed hosts use the
same provider; the API root is `<base URL>/api/v4`.

## Choose the provider and the host

Set the provider per project in the registry, and the host where it is not `gitlab.com`:

```yaml
projects:
  - match: platform/payments-api
    provider: gitlab
    base_url: https://gitlab.example.com
    auth:
      token_secret: gitlab-payments-token
    extends: strict
```

`vcs.provider: auto` infers the provider only for `gitlab.com` and `github.com`. For a self-managed host,
set `provider` explicitly, otherwise the project is unavailable and the run records a warning.

## The bot identity

Create a dedicated bot account, preferably a **project access token** (or a group access token). GitLab
creates a bot user whose login looks like `project_<id>_bot`. Set that login as `vcs.bot_username` in the
organisation file or the project's registry entry.

`vcs.bot_username` is required. Without it, every webhook event for the project is ignored. The squad
uses it to ignore its own comments and events, which prevents a review loop.

Scopes, role and rotation are described in `examples/gitlab/token-scopes.md` in the repository. In short:
role Developer, scopes `api` and `read_repository`, plus `write_repository` only when `pam` pushes branches.

## Connect the events

Two options:

1. **CI job** (no inbound route). `examples/gitlab/gitlab-ci-snippet.yml` defines a job that runs on
   merge request pipelines, calls michael's `/invocations` and stores the result as an artifact. The
   `SQUAD_POST` variable controls publication; the default is a dry run.
2. **Webhook** (the squad receives the events). Set `WEBHOOK_PROVIDERS=gitlab` on michael, store the
   secret as `gitlab-webhook-secret`, and add a project webhook with the URL `https://<squad host>/webhooks/gitlab`.
   Enable merge request events and comments. Details and troubleshooting are in
   `examples/gitlab/webhook-setup.md` in the repository.

The secret token is compared in constant time with the `X-Gitlab-Token` header. A wrong token returns `401`.

## Capabilities on GitLab

| Capability | GitLab |
| --- | --- |
| Commit statuses (`ai-review/<agent>`) | Yes. This is the verdict signal. |
| Check runs | No. Not used. |
| Batched review | No. Inline comments are posted as discussions. |
| Formal approval | Yes, only when `vcs.approve_mode` allows it. |
| Draft merge requests | Yes, when `implementer.mr_draft` is true. |
| Resolve threads | Supported by the provider, not used by the publication path. |
| Job logs | Yes. Used by darryl, trimmed to the failure region. |
| Issues | Yes. Used as task text and for comments on issues. |
| Push | Yes, over HTTPS with the project token, for `pam`. |

The full matrix, with the fallbacks, is in the [capability reference](../reference/vcs-capabilities.md).

## Self-managed notes

- The base URL is the instance root, for example `https://gitlab.example.com`. The provider appends `/api/v4`.
- If the instance uses a private certificate authority, the squad image must trust it. The platform has no
  setting for an extra CA bundle (open point; see [Network and egress](../deployment/network-and-egress.md)).
- The squad needs outbound HTTPS to the instance. Put the instance's address in `networkPolicy.vcsCIDRs`
  or route through `egressProxy.url`.
- Protected-branch checks use the protected-branches endpoint. The bot needs permission to read it.

## Rate limits and retries

The HTTP client retries `429` and `5xx` responses up to 4 times. It honours the `Retry-After` header when
present; otherwise it backs off exponentially, capped at 30 seconds, with jitter. A single wait never
exceeds 120 seconds. Requests time out after 30 seconds. List calls follow pagination up to 100 pages.

A `429` that persists is reported as a rate-limit error for the operation. The run records a warning, and
the verdict is `incomplete` when a specialist could not read the change.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| Webhook returns `404` | `WEBHOOK_PROVIDERS` does not include `gitlab`. |
| Webhook returns `401` | The secret in GitLab differs from `gitlab-webhook-secret`. |
| Webhook answers `ignored` with a `bot_username` reason | Set `vcs.bot_username` for the project. |
| Run warns "VCS unavailable" | The token secret name is wrong, the secret is missing, or the provider cannot be inferred. |
| Verdict is `incomplete`, status `pending` | A specialist could not read the change, or a rate limit persisted. Read the summary. |
| Status is set but no discussions appear | Comment style is `summary`, or findings are below `review.min_severity_inline`. Check `vcs.comment_style` and the summary. |
| pam cannot push | The token lacks `write_repository`, or the branch is protected. |
