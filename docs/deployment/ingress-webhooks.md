# Ingress and webhooks

Only two paths of the squad are meant to be reachable from outside the cluster: the GitLab and GitHub webhook
receivers of `michael`. The chart's Ingress routes exactly those two paths, with `pathType: Exact`, and nothing else.
Every other path, including `/invocations`, is not routed through the ingress.

## What the chart exposes

| Path | Backend | Enabled when |
| --- | --- | --- |
| `/webhooks/gitlab` | Service `code-squad-michael`, port `http` | `ingress.enabled` and `webhooks.gitlab.enabled` |
| `/webhooks/github` | Service `code-squad-michael`, port `http` | `ingress.enabled` and `webhooks.github.enabled` |

Set the host, the class and TLS with `ingress.host`, `ingress.className` and `ingress.tls`. Annotations go in
`ingress.annotations`, for example a request body size limit or a rate limit supported by your controller.

## Enable michael's webhook routes

The chart sets `WEBHOOK_PROVIDERS` on michael from `webhooks.gitlab.enabled` and `webhooks.github.enabled`, and
michael registers a route only for the providers named there. Disable a provider by setting its flag to `false`;
its path is then not exposed and its route is not registered. Without the variable, `POST /webhooks/gitlab` returns
`404` from michael.

## Secrets for signature checks

Each provider has a signing secret that michael verifies on every delivery:

| Provider | Secret name | Header | Check |
| --- | --- | --- | --- |
| GitLab | `gitlab-webhook-secret` | `X-Gitlab-Token` | Constant-time comparison with the stored value |
| GitHub | `github-webhook-secret` | `X-Hub-Signature-256` | HMAC-SHA256 of the raw body, constant-time comparison |

The secrets come from `secrets.existingSecret`, or from a separate Secret named in `webhooks.secretName`
(mounted only on michael). A missing secret means every delivery for that provider is refused with `401`.

## Test a delivery

Test a GitHub-style signature from a shell without writing the secret into a file. The body and the secret are
placeholders here:

```bash
BODY='{"action":"opened","pull_request":{"number":42}}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$GITHUB_WEBHOOK_SECRET" | sed 's/^.* //')
DELIVERY=$(uuidgen)
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "https://squad.example.com/webhooks/github" \
  -H 'content-type: application/json' \
  -H 'x-github-event: pull_request' \
  -H "x-github-delivery: $DELIVERY" \
  -H "x-hub-signature-256: sha256=$SIG" \
  --data "$BODY"
```

Expected results: `202` (accepted or ignored, with a reason in the body), `401` for a wrong signature, `400` for a body
that is not a JSON object, and `200` with `duplicate` when a delivery with the same id is sent again. The id is the
`X-GitHub-Delivery` header for GitHub and `X-Gitlab-Event-UUID` for GitLab, so repeat the request with the same value to
see the duplicate answer. An event for a project
with no registry entry, or without `vcs.bot_username`, is `202` with `ignored` and the reason. The response body
explains which.

For GitLab, send the token itself in `X-Gitlab-Token` over HTTPS.

## What the webhook does not protect

The signature protects the webhook path only. `/invocations` is not behind the ingress. When `api.tokenSecret` is set,
the squad requires the shared bearer token on `/invocations` and `/jobs/{id}`, but that token is not a substitute for
keeping the path internal. Options, in order of preference:

1. Keep it internal. Callers are CI jobs inside the cluster, which reach the Service directly, with the bearer token.
2. Put an authenticating proxy (for example one that validates a client certificate) in front of a dedicated ingress
   host for `/invocations`.
3. Use mTLS at the ingress controller and restrict the route to the client certificates you issue.

Do not add a route for `/invocations` to the ingress without one of these in front of it. See
[Hardening](../security/hardening.md#api-authentication).

## Operational notes

- Webhook deliveries are answered with `202` before the review runs. A review that fails later is visible in the logs
  and in `squad_invocations_total{status="failed"}`, not in the HTTP response.
- Deliveries are de-duplicated per replica in memory. With more than one replica, a redelivery may be processed by
  another replica. See [Scaling and upgrades](scaling-upgrades.md).
- The gateway trusts the signature, not the source address. Rate limiting at the ingress is still worth having.
