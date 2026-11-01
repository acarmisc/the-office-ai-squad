# RBAC

The squad has two places where it touches the cluster API: `darryl`, which reads state for troubleshooting, and
`pam`, which creates and removes sandbox pods. Every other agent has no Kubernetes permission. This page lists
exactly what each service account can do, how to check it, and what the chart does not grant.

## Service accounts

- The chart creates one ServiceAccount per enabled agent, named `code-squad-<id>`, in the release namespace. Set
  `serviceAccount.create: false` and `serviceAccount.name` to use one existing account for all agents. Then the
  darryl and pam bindings point at that name.
- Only `darryl` and `pam` mount a ServiceAccount token (`automountServiceAccountToken: true`). The other pods do
  not, which removes a credential from their reach.
- Annotations in `serviceAccount.annotations` are applied to every ServiceAccount, for example for workload identity.

## darryl: read-only cluster access

Two modes, set in `devops`:

| Mode | Setting | Object created | Scope |
| --- | --- | --- | --- |
| Per namespace (default) | `devops.allowedNamespaces: [ns1, ns2]` | A Role `code-squad-devops-read` and a RoleBinding in each listed namespace | Those namespaces only |
| Cluster-wide (discouraged) | `devops.clusterWide: true` | A ClusterRole `code-squad-devops-read` and a ClusterRoleBinding | Every namespace; ignores the list |

Granted verbs are `get`, `list` and `watch`, and nothing else, on:

| API group | Resources |
| --- | --- |
| core | `pods`, `pods/log`, `events`, `services`, `endpoints`, `configmaps` |
| `apps` | `deployments`, `replicasets`, `statefulsets`, `daemonsets`, `controllerrevisions` |
| `metrics.k8s.io` | `pods` (get, list only) |
| core, cluster-wide mode only | `nodes` (get, list) and `metrics.k8s.io` `nodes` |

Not granted: `secrets` (in any mode), any write verb, `exec`, `pods/exec`, `portforward`, RBAC objects, or any
custom resource. The client code adds its own checks: the namespace must be in `ops.allowed_namespaces`, and any
kind that contains "secret" is refused before the request is sent.

Config maps are readable. Their values pass through the redactor before the model sees them, but their keys and
their non-secret values are visible. Keep secrets out of config maps. This is the largest residual risk of the
darryl grant, and it is listed in the [threat model](../security/threat-model.md).

## pam: sandbox pod lifecycle

pam needs to create and remove sandbox pods and run commands in them. The chart grants this in the sandbox
namespace only, through a Role `code-squad-sandbox-runner` and a RoleBinding `code-squad-pam-sandbox`:

| Resource | Verbs |
| --- | --- |
| `pods` | create, get, list, delete, watch |
| `pods/exec` | create |
| `pods/log` | get |

This is the only write permission in the chart. It is confined to the sandbox namespace, which the chart does not
create. Create it yourself with the restricted Pod Security label, so the namespace enforces the pod restrictions even
if the squad's own pod spec were wrong.

The sandbox pods themselves run with no service account token (`automountServiceAccountToken: false`), so a
repository script inside a sandbox has no Kubernetes identity.

## What the chart does not grant

- No agent can read secrets through the API.
- No agent can change workloads, config maps, secrets, RBAC or namespaces.
- No agent can exec into an agent pod. `pods/exec` exists only in the sandbox namespace.
- Only the sandbox namespace is writable, and only by pam.

## Verify the grants

Use `kubectl auth can-i` with the service account, and check that each answer matches the table above:

```bash
SA=system:serviceaccount:code-squad:code-squad-darryl
kubectl auth can-i get pods -n squad-staging --as "$SA"        # yes
kubectl auth can-i get secrets -n squad-staging --as "$SA"     # no
kubectl auth can-i delete pods -n squad-staging --as "$SA"     # no

SA=system:serviceaccount:code-squad:code-squad-pam
kubectl auth can-i create pods -n code-squad-sandbox --as "$SA"   # yes
kubectl auth can-i create pods -n squad-staging --as "$SA"        # no
```

Any answer that differs from the table is a deployment problem. Fix the values before you run the squad.

## Admission and Pod Security

- The agent pods run as uid 10001 with a read-only root filesystem, no capabilities and the `RuntimeDefault` seccomp
  profile. They satisfy the restricted Pod Security Standard.
- Sandbox pods run as uid 10002 with the same restrictions and a deadline, and the sandbox namespace must enforce
  `restricted`.
