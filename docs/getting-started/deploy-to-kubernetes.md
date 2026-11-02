# Deploy to Kubernetes (about 15 minutes)

This page installs the released chart and images for the first time, in dry-run mode, and shows how to check that the squad works
before it is allowed to write to your VCS. It covers the minimal set of agents: `michael` (orchestrator), `jim`, `angela` and `dwight`.
`darryl` and `pam` stay off until you need them, because each one needs extra access (the Kubernetes API and a sandbox namespace).

If you do not want a cluster, the [GitHub Actions review](../vcs/github-actions.md) runs the same agents inside a pull request job.

Every step names the command to run. Replace the example hosts (`*.example.com`), the RFC 5737 addresses (`192.0.2.0/24`,
`198.51.100.0/24`) and the project path with your own values. The values file is checked by the test suite against the chart schema,
so a key that the chart does not accept fails the docs build.

## Before you start

| You need | Why | Where to read more |
| --- | --- | --- |
| Kubernetes 1.30 or later, with a CNI that enforces NetworkPolicy | The sandbox uses the exec API; policies are otherwise accepted and not enforced | [Helm chart](../deployment/helm.md#prerequisites) |
| An OpenAI-compatible LiteLLM gateway reachable from the cluster, serving the names `haiku-5-5` and `sonnet-5-5` | Every model call goes through it | Step 3 below |
| A bot identity on GitLab or GitHub with the smallest scopes | Reads diffs, posts comments and the commit status | [GitLab](../vcs/gitlab.md#the-bot-identity), [GitHub](../vcs/github.md#create-the-app) |
| `helm` 3, `kubectl`, `openssl`, `jq`, `curl` | Install, secrets and the verification commands | |
| This repository checked out at the release tag, or the OCI chart | Values examples and scripts | [Images, charts and releases](../deployment/images-and-releases.md) |

Pick the release you are installing. The examples use `0.1.0`:

```bash
helm show chart oci://ghcr.io/acarmisc/charts/code-squad --version 0.1.0
docker pull ghcr.io/acarmisc/code-squad:0.1.0
```

[Images, charts and releases](../deployment/images-and-releases.md) lists every artifact, its digest and the verification steps.

## Step 1: namespaces

```bash
kubectl create namespace code-squad
```

Create the sandbox namespace only when `pam` is enabled. Its Pod Security label is required:

```bash
kubectl create namespace code-squad-sandbox
kubectl label namespace code-squad-sandbox pod-security.kubernetes.io/enforce=restricted
```

## Step 2: secrets

The chart mounts one Secret into every agent at `/var/run/secrets/squad`. Each key becomes a file named after the key. Use values
from your own secret store; the examples read them from the environment. Never commit them.

```bash
kubectl -n code-squad create secret generic code-squad-secrets \
  --from-literal=llm-api-key="$LLM_API_KEY" \
  --from-literal=gitlab-web-app-token="$GITLAB_BOT_TOKEN"

kubectl -n code-squad create secret generic code-squad-api \
  --from-literal=api-token="$(openssl rand -hex 32)"
```

- `llm-api-key` is the gateway key. The chart exposes it to every agent as the environment variable `LLM_API_KEY`, read from
  that key (`llm.apiKeySecret.key` defaults to the name). The Secret's keys are also mounted as files under `/var/run/secrets/squad`.
- `gitlab-web-app-token` is the name the project registry refers to (`auth.token_secret`). For GitHub use a `private_key_secret`
  holding the App's PEM text instead.
- `code-squad-api` holds the shared bearer token that `/invocations` requires. The chart fails closed without it. Keep the value; the
  trial script sends it.

Check the keys without printing the values:

```bash
kubectl -n code-squad get secret code-squad-secrets -o json | jq -r '.data | keys[]'
```

The full secret model, rotation and what each pod can read are in [Secrets](../deployment/secrets.md).

## Step 3: the LLM gateway

The squad sends the model names `haiku-5-5` and `sonnet-5-5` to the gateway unchanged. The gateway must map those names to a real
upstream model. The configuration below is an **example** of that mapping. The exact schema depends on your LiteLLM version, so check
the [LiteLLM proxy configuration documentation](https://docs.litellm.ai/docs/proxy/configs) and replace each placeholder:

```yaml
# Example only: LiteLLM proxy config. Replace the placeholders; verify the schema
# against the LiteLLM version you run.
model_list:
  - model_name: haiku-5-5
    litellm_params:
      model: <provider>/<small-model-id>
  - model_name: sonnet-5-5
    litellm_params:
      model: <provider>/<large-model-id>
```

Check that the gateway answers before you install:

```bash
curl -sS https://litellm.example.com/v1/models -H "Authorization: Bearer $LLM_API_KEY" | jq -r '.data[].id'
```

The output must include both aliases. The chart's `llm.baseUrl` is the gateway's `/v1` URL. A request for a model that is not in
`llm.allowed_models` is refused with `422` before any model call.

## Step 4: the values file

Save this as `my-values.yaml`. It is the smallest set that renders and runs in dry-run mode. It turns off the webhooks, `darryl` and
`pam`, and forces dry run for every project.

<!-- validate: helm-values -->
```yaml
image:
  repository: ghcr.io/acarmisc/code-squad
  tag: "0.1.0"
llm:
  baseUrl: https://litellm.example.com/v1
secrets:
  existingSecret: code-squad-secrets
api:
  tokenSecret:
    name: code-squad-api
    key: api-token
webhooks:
  gitlab:
    enabled: false
  github:
    enabled: false
agents:
  michael:
    model: haiku-5-5
  jim:
    model: sonnet-5-5
  angela:
    model: sonnet-5-5
  dwight:
    model: sonnet-5-5
  darryl:
    enabled: false
  pam:
    enabled: false
config:
  org:
    llm:
      allowed_models: [haiku-5-5, sonnet-5-5]
    posting:
      force_dry_run: true
    vcs:
      bot_username: "project_123_bot"
  projects:
    projects:
      - match: acme/web-app
        provider: gitlab
        base_url: https://gitlab.example.com
        auth:
          token_secret: gitlab-web-app-token
        extends: balanced
networkPolicy:
  llmGatewayCIDRs:
    - 192.0.2.10/32
  vcsCIDRs:
    - 192.0.2.0/24
```

The organisation file that the `config.org` block renders into `squad.yaml`:

<!-- validate: config:org -->
```yaml
llm:
  allowed_models: [haiku-5-5, sonnet-5-5]
posting:
  force_dry_run: true
vcs:
  bot_username: "project_123_bot"
```

The project registry that the `config.projects` block renders into `projects.yaml`:

<!-- validate: projects -->
```yaml
projects:
  - match: acme/web-app
    provider: gitlab
    base_url: https://gitlab.example.com
    auth:
      token_secret: gitlab-web-app-token
    extends: balanced
```

What each setting does:

- `llm.baseUrl` and `llm.allowed_models`: where model calls go, and which model names may be requested.
- `secrets.existingSecret`, `api.tokenSecret`: the secrets from step 2.
- `networkPolicy.llmGatewayCIDRs` and `vcsCIDRs`: NetworkPolicy takes IP ranges, not hostnames. Use the gateway's and your VCS
  host's addresses, or route outbound traffic through a proxy (`egressProxy`). Without them the agents cannot reach those hosts.
- `posting.force_dry_run: true`: no agent can write to the VCS. You switch this off only at step 8 of
  [the new project checklist](../onboarding/new-project.md).
- `vcs.bot_username`: the bot's login. Without it the squad ignores events for the project.

Render the chart before installing. This catches a missing key without touching the cluster:

```bash
helm template code-squad oci://ghcr.io/acarmisc/charts/code-squad --version 0.1.0 \
  --namespace code-squad -f my-values.yaml > rendered.yaml
kubeconform -strict -summary -ignore-missing-schemas rendered.yaml
```

## Step 5: install

```bash
helm upgrade --install code-squad oci://ghcr.io/acarmisc/charts/code-squad --version 0.1.0 \
  --namespace code-squad -f my-values.yaml
kubectl -n code-squad rollout status deploy/code-squad-michael --timeout=180s
```

Install with the chart from this repository instead when you test a commit: `helm upgrade --install code-squad deploy/helm/code-squad
--namespace code-squad -f my-values.yaml`. The values keys are the same.

## Step 6: verify that it runs

Forward the orchestrator and the specialists to your workstation:

```bash
kubectl -n code-squad port-forward svc/code-squad-michael 8080:8080 >/dev/null &
kubectl -n code-squad port-forward svc/code-squad-jim 8081:8080 >/dev/null &
kubectl -n code-squad port-forward svc/code-squad-angela 8082:8080 >/dev/null &
kubectl -n code-squad port-forward svc/code-squad-dwight 8083:8080 >/dev/null &
for port in 8080 8081 8082 8083; do curl -sS "localhost:${port}/ready"; echo; done
```

Each line must be `{"status":"ready","agent":"..."}`. `/ready` only proves that the agent's specification loaded. It does not call
the gateway, so the dry run in step 7 is the real test.

Check the protections:

```bash
# No token: must be 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST localhost:8080/invocations \
  -H 'content-type: application/json' -d '{"prompt":"x","post":false}'
# Webhooks are off in this file: must be 404
curl -sS -o /dev/null -w '%{http_code}\n' -X POST localhost:8080/webhooks/gitlab
```

## Step 7: the first dry run

Choose one small change request in the registered project. The script sends the review with `post: false` and prints a report:

```bash
export SQUAD_API_TOKEN="$(kubectl -n code-squad get secret code-squad-api -o jsonpath='{.data.api-token}' | base64 -d)"
scripts/trial_review.sh http://localhost:8080 acme/web-app 42
```

The request the script sends is equivalent to this:

<!-- validate: invocation -->
```json
{"prompt": "review change request 42", "project": "acme/web-app", "target": "42", "mode": "review", "post": false}
```

Read the report. It must show `posted: notes=0 discussions=0 status=None`. A dry run that tried to write also lists the blocked
attempts in `warnings`. The report does not print the findings; to read them, send the same JSON body with `curl` to `/invocations` and
read the `findings` array. Check the file, the line range and the rationale of each finding. A warning about a rejected configuration layer, an unavailable provider or a
missing skill must be fixed before you go live. The full acceptance procedure is [First operational test](../operations/first-operational-test.md).

## Step 8: go live

Do this only after several dry runs look right:

1. Set `config.org.posting.force_dry_run` to `false` in `my-values.yaml` and run the install command again. The organisation file is
   hot-reloaded; the next request reads it.
2. Enable one way of triggering reviews: webhooks (`webhooks.gitlab.enabled` or `webhooks.github.enabled`, then the steps in
   [Ingress and webhooks](../deployment/ingress-webhooks.md)), or a CI job from [GitLab](../vcs/gitlab.md) or [GitHub](../vcs/github.md).
3. Set `trigger.allowed_commenters` before enabling comment commands.
4. Do not make `ai-review/michael` a required status in branch protection until the team trusts the verdicts.
5. Turn on monitoring: `serviceMonitor.enabled` and the alert rules in the [runbook](../operations/runbook.md).
6. Enforce the policies. Confirm that your CNI enforces NetworkPolicy by running a test pod that cannot reach a blocked address.
7. Pin the image by digest for production; see [Images, charts and releases](../deployment/images-and-releases.md).

## Next steps

- Add the repository to the squad: [New project checklist](../onboarding/new-project.md).
- Enable `darryl` or `pam` later: [Helm chart](../deployment/helm.md#example-values-files) lists the example values for each.
- Something failed? [Troubleshooting](troubleshooting.md) maps symptoms to causes and fixes.
