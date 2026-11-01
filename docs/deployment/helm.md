# Helm chart

The chart in `deploy/helm/code-squad` installs the squad on any Kubernetes cluster that supports the
restricted Pod Security Standard. One image serves every agent, and each agent is a Deployment and a Service
named `code-squad-<id>`. The chart values are checked against `values.schema.json`, which rejects unknown
keys. The reference below walks through each section; the authoritative defaults are in `values.yaml`.

## What the chart renders

| Object | Per | Condition |
| --- | --- | --- |
| Deployment, Service, ServiceAccount | Agent | `agents.<id>.enabled` |
| NetworkPolicy (default deny, then allow-lists) | Agent | `networkPolicy.enabled` |
| ConfigMap `code-squad-config` (`squad.yaml`) and `code-squad-projects` (`projects.yaml`) | Release | Always |
| Role and RoleBinding in each allowed namespace, or a ClusterRole for darryl | Namespace | `devops.allowedNamespaces`, or `devops.clusterWide` |
| Role and RoleBinding for pam in the sandbox namespace, sandbox NetworkPolicy | Release | `sandbox.enabled` and pam enabled |
| Ingress `code-squad-webhooks` | Release | `ingress.enabled` (only the webhook paths) |
| HorizontalPodAutoscaler | Agent | `hpa.enabled` |
| PodDisruptionBudget | Agent | `pdb.enabled` |
| ServiceMonitor | Agent | `serviceMonitor.enabled` (Prometheus Operator CRD required) |

The chart does not create the sandbox namespace. Create it with the restricted Pod Security label before
installing.

## Prerequisites

- Kubernetes 1.27 or later (`kubeVersion` in `Chart.yaml`). The sandbox needs the exec protocol that file
  writes use, which is Kubernetes 1.30 or later.
- A CNI that enforces NetworkPolicy. Without it, the policies are accepted and not enforced.
- A LiteLLM-compatible gateway reachable from the cluster.
- The Secret described in [Secrets](secrets.md), created before the first install.
- An ingress controller, when webhooks are used.
- The Prometheus Operator, when `serviceMonitor.enabled` is true.

## Install

```bash
kubectl create namespace code-squad
kubectl create namespace code-squad-sandbox
kubectl label namespace code-squad-sandbox pod-security.kubernetes.io/enforce=restricted

helm lint deploy/helm/code-squad -f my-values.yaml
helm upgrade --install code-squad deploy/helm/code-squad \
  --namespace code-squad --create-namespace -f my-values.yaml
```

Start from one of the example values files in `deploy/helm/code-squad/values-examples/` and override only what
differs. The examples are listed below.

## Values walkthrough

| Section | Purpose | Notes |
| --- | --- | --- |
| `image` | Repository, tag and pull policy | An empty tag means `Chart.appVersion`. |
| `imagePullSecrets` | Registry credentials | |
| `agents.<id>` | Enable, replicas, resources, extra env, model name | Keys are fixed: `michael`, `jim`, `angela`, `dwight`, `darryl`, `pam`. `env` appends environment variables to one agent. |
| `llm` | Gateway URL and the Secret key for the gateway key | `LLM_BASE_URL` and `LLM_API_KEY` are set from here. |
| `vcs` | Default provider and base URL | `provider: auto` infers only for github.com and gitlab.com. Set `gitlab` or `github` for self-managed hosts. |
| `secrets.existingSecret` | Name of the Secret mounted at `/var/run/secrets/squad` | Every agent mounts the whole Secret. |
| `api.tokenSecret.name`, `api.tokenSecret.key` | Optional shared bearer token for `/invocations` and `/jobs/{id}` | Empty means no token check. Set on every agent as `SQUAD_API_TOKEN`; see [Authentication](#authentication). |
| `config.org` | Organisation file content (`squad.yaml`) | Free-form YAML, rendered verbatim. |
| `config.projects` | Project registry content (`projects.yaml`) | Free-form YAML, rendered verbatim. |
| `config.restartOnChange` | Roll pods when config changes | Off: files are hot-reloaded. |
| `otel.endpoint` | OTLP/HTTP collector | Empty disables trace export. |
| `sessionStore.url` | Redis URL for asynchronous jobs | Empty means in-process state; see scaling. |
| `egressProxy.url` | Outbound proxy | When set, add proxy CIDRs to `networkPolicy.egressProxyCIDRs`. |
| `webhooks.gitlab.enabled`, `webhooks.github.enabled` | Which webhook paths the ingress exposes | Also sets `WEBHOOK_PROVIDERS` on michael, so the route is registered. |
| `webhooks.secretName` | Optional separate Secret for the webhook secrets | Mounted on michael at `/var/run/secrets/squad-webhooks`. |
| `ingress` | Ingress class, host, TLS, annotations | Routes only `/webhooks/gitlab` and `/webhooks/github`, to michael. |
| `serviceMonitor` | Metrics scraping | Scrapes `/metrics` on each agent. |
| `hpa`, `pdb` | Autoscaling and disruption budget | See [Scaling and upgrades](scaling-upgrades.md). |
| `serviceAccount` | One ServiceAccount per agent, or one shared name | Annotations for workload identity. |
| `networkPolicy` | DNS, LLM gateway, VCS, OTLP, proxy, session store, advisory and API-server CIDRs | Hostnames are not allowed in NetworkPolicy; use CIDRs or the proxy. |
| `devops` | Namespaces where darryl may read, or cluster-wide read | Keep in step with `ops.allowed_namespaces` in the org file. |
| `sandbox` | Sandbox namespace, image, resources, deadline and TTL | Enables the Kubernetes sandbox for pam. |
| `podSecurityContext`, `containerSecurityContext` | Restricted Pod Security settings | Non-root, read-only root filesystem, no capabilities. |

### Webhooks

`webhooks.gitlab.enabled` and `webhooks.github.enabled` do two things: the ingress exposes the matching path, and
the chart sets `WEBHOOK_PROVIDERS` on michael to the same providers (`gitlab`, `github`, or `gitlab,github`). michael
registers only the routes named there. With both flags false, `WEBHOOK_PROVIDERS` is empty and no webhook route exists.

### Authentication

Set `api.tokenSecret.name` to a Secret that holds the token under `api.tokenSecret.key` (default `api-token`). Every
agent then receives `SQUAD_API_TOKEN` from that Secret. `POST /invocations` and `GET /jobs/{id}` require
`Authorization: Bearer <token>`, and michael sends the same header to the specialists. `/ping`, `/ready`, `/metrics`
and the webhook routes are not gated by the token; webhooks keep their own signature checks.

```yaml
api:
  tokenSecret:
    name: code-squad-api
    key: api-token
```

With the token unset, each pod logs one warning at start-up and the endpoints are open. Network policy and the
ingress are then the only protection. See [Hardening](../security/hardening.md#api-authentication).

### Keys to keep consistent

- `devops.allowedNamespaces` and `ops.allowed_namespaces` (organisation file) must list the same namespaces.
  The schema key is `ops.allowed_namespaces`.
- `agents.<id>.model` sets `AGENT_MODEL_ID`. The value is sent to the LLM gateway unchanged; no alias map is applied.
- `sandbox.enabled` controls the Kubernetes sandbox. When it is false, pam uses the local process sandbox
  inside its own container. Keep it true outside a disposable test cluster; see [pam](../agents/pam.md).

### An example values overlay

The block below is validated by the test suite against the chart's schema. Replace every placeholder, and use
the RFC 5737 documentation addresses only as placeholders.

<!-- validate: helm-values -->
```yaml
image:
  repository: registry.example.com/platform/code-squad
  tag: "0.1.0"
llm:
  baseUrl: https://litellm.example.com/v1
vcs:
  provider: auto
secrets:
  existingSecret: code-squad-secrets
agents:
  michael:
    replicas: 1
webhooks:
  gitlab:
    enabled: true
  github:
    enabled: true
ingress:
  enabled: true
  className: nginx
  host: squad.example.com
  tls:
    - hosts:
        - squad.example.com
      secretName: squad-tls
devops:
  allowedNamespaces:
    - squad-staging
sandbox:
  enabled: true
  namespace: code-squad-sandbox
  image: registry.example.com/platform/code-squad-sandbox-node:0.1.0
networkPolicy:
  llmGatewayCIDRs:
    - 192.0.2.10/32
  vcsCIDRs:
    - 192.0.2.0/24
  advisoryCIDRs:
    - 198.51.100.0/24
```

The organisation file that the same deployment would render into `config.org`:

<!-- validate: config:org -->
```yaml
vcs:
  approve_mode: none
  bot_username: code-squad-review[bot]
trigger:
  on_push: false
posting:
  force_dry_run: false
repo_config:
  allow_head_ref: false
limits:
  max_tokens: 200000
  max_iterations: 50
```

## Example values files

| File | Use it for |
| --- | --- |
| `minimal-kind.yaml` | Local kind demo with the in-cluster fake LLM. Network policies and the sandbox are off. Not for production. |
| `gitlab-only.yaml` | GitLab only, self-managed. Only `/webhooks/gitlab` is routed. Replace the RFC 5737 placeholder CIDRs. |
| `github-app.yaml` | GitHub with a GitHub App. Secrets for the App key and webhook secret come from `code-squad-secrets`. |
| `multi-provider.yaml` | GitLab and GitHub side by side. The registry maps each project to its provider. |
| `production-ha.yaml` | Two or three replicas per agent, autoscaling, disruption budget, zone spreading, metrics and TLS on webhooks. |
| `egress-proxy-airgapped.yaml` | All outbound HTTPS through a proxy. Advisory CIDRs are empty on purpose; dwight then runs in offline mode unless the proxy allows the advisory hosts. |
| `external-secrets.yaml` | Secrets from External Secrets Operator. The chart only references the Secret. |

Every example file validates against the schema in the test suite. Their comments name what to replace.

## Upgrade and rollback

See [Scaling and upgrades](scaling-upgrades.md). In short: `helm upgrade` with the new image tag,
`helm history` to find the previous revision, and `helm rollback` to revert.
