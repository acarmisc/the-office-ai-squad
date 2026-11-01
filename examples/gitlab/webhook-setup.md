# GitLab webhook setup

Use a webhook when reviews should start from GitLab events rather than from a CI job. The
CI job in `gitlab-ci-snippet.yml` is the simpler option and needs no inbound route.

## What michael needs before it accepts deliveries

1. The `gitlab` provider is enabled on michael: `WEBHOOK_PROVIDERS=gitlab`. The Helm chart
   does not set this variable; add it under `agents.michael.env` in the values file.
2. A signing secret named `gitlab-webhook-secret` is readable by michael, either as a key of
   the Secret in `secrets.existingSecret` or as a file in the directory named by
   `WEBHOOK_SECRETS_DIR`.
3. The organisation configuration (or the project's registry entry) sets `vcs.bot_username`
   to the login of the bot account. Without it every event is ignored, which prevents the
   squad from reacting to its own comments.
4. The project has a registry entry, so `vcs.provider` and the token secret name resolve.

## Create the webhook

In the GitLab project, open **Settings > Webhooks** and add:

| Field | Value |
| --- | --- |
| URL | `https://<squad host>/webhooks/gitlab` |
| Secret token | the value of `gitlab-webhook-secret` |
| Trigger: Merge request events | on |
| Trigger: Comments | on, so that `@<bot>` mentions and `/squad` commands work |
| Trigger: Push events | off unless `trigger.on_push` is true for the project |
| Trigger: Issue events | on only when `pam` should pick up issues assigned to the bot |
| SSL verification | on |

GitLab sends the secret in the `X-Gitlab-Token` header. michael compares it with the stored
secret in constant time. A delivery with a wrong or missing token gets `401`.

## What the endpoint answers

| Response | Meaning |
| --- | --- |
| `202` with `status: accepted` | A review job was started. Poll nothing: the result is posted to the change request. |
| `202` with `status: ignored` | The event does not qualify: draft, skip label, WIP title, unauthorised commenter, or no request for the bot. The `reason` field says which rule applied. |
| `200` with `status: duplicate` | This delivery id was already handled. |
| `400` | The body is not a JSON object. |
| `401` | The token does not match. |
| `503` | The organisation configuration is invalid. Fix it and redeliver. |

## Test a delivery

GitLab's **Test** button sends a sample event. Expect `202` with `ignored` for a sample that is
not a change request for the bot. A real review request from a reviewer assigned to the bot
should give `accepted`. Use the project's dry-run setting (`posting.force_dry_run` or
`post: false` from the caller) for the first runs.

## Troubleshooting

- Always `404`: `WEBHOOK_PROVIDERS` does not include `gitlab`, or the ingress routes to a
  different service.
- Always `401`: the stored secret and the value typed in GitLab differ. Files from the
  Kubernetes secret provider lose only trailing line breaks; files in `WEBHOOK_SECRETS_DIR`
  lose all surrounding whitespace. Any other space is part of the secret, so store the value
  exactly as typed in GitLab.
- `ignored` with "vcs.bot_username is not configured": set `vcs.bot_username`.
- Repeated deliveries for one change: the debounce window (`trigger.debounce_seconds`)
  collapses bursts for the same head commit.
