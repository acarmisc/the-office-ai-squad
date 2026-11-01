# Scaling, high availability and upgrades

The squad is mostly stateless. Each request carries everything the agent needs, and the state that survives a request is in the VCS
host. The exceptions are michael's job store and webhook de-duplication, which live in memory. That decides how michael can be scaled.
This page covers the replica rules per agent, the sizing levers, the upgrade and rollback procedure, and the image architectures.

## Replicas per agent

| Agent | State | Scale out | Notes |
| --- | --- | --- | --- |
| `jim`, `angela`, `dwight`, `darryl` | None between requests (advisory cache and NVD throttle are per run) | Yes | Horizontal scaling and the HPA work. Model calls dominate latency. |
| `pam` | None between requests; each run has its own sandbox pod | Yes | Each run needs room for a sandbox pod in the sandbox namespace. Size the namespace quota for the concurrent runs you expect. |
| `michael` | Job store and webhook de-duplication in memory, per replica | Only with care | See below. |

### michael and the in-memory state

- A webhook is answered on the replica that received it, and its job runs there. A later `GET /jobs/<id>` for that job returns
  `404` on any other replica.
- A redelivery may reach a different replica, which cannot see the first delivery's record. Both replicas may run the review. The
  publication is idempotent by markers, so the result is a duplicated run rather than duplicated comments, but it costs model calls.
- The debounce window is also per replica, so a burst split across replicas can produce several runs for one head.

Options, in order of preference:

1. **One replica of michael** for webhook-driven reviews, with a PodDisruptionBudget only if you accept that it blocks drains. The
   chart default is one replica.
2. **A shared session store.** `SESSION_STORE_URL` set to a Redis URL moves job state to Redis. The de-duplication and debounce still
   live in memory, so this is not a complete fix. The image installs the `redis` extra (`uv sync --extra redis` in
   `deploy/Dockerfile`), so a `redis://` or `rediss://` URL is accepted at start-up without a custom build. A custom image must
   keep the extra too, or the Redis URL fails at start-up.
3. **Session affinity** on the michael Service for the polling path. Affinity does not fix webhook de-duplication across replicas.

Direct `POST /invocations` calls with `Prefer: respond-async` have the same limitation: poll the same replica, or use a single replica.

## Sizing levers

| Lever | Where | Effect |
| --- | --- | --- |
| Specialist concurrency | `routing.fan_out_concurrency` (default 4) | Parallel specialist calls per review; more parallelism costs more gateway capacity. |
| Specialist timeouts | `routing.timeouts_seconds` | A specialist that exceeds its timeout makes the verdict `incomplete`. Raise it before you add replicas to fix a timeout. |
| Model turn and token limits | `agents.<id>.max_iterations`, `max_tokens`, `limits.*` | Bound the work per run. |
| Debounce | `trigger.debounce_seconds` | Fewer runs during bursts of pushes. |
| Resources | `agents.<id>.resources`, `sandbox.resources` | Requests and limits per pod. pam and the sandbox need the most memory for builds. |
| HPA | `hpa.enabled`, `hpa.minReplicas`, `hpa.maxReplicas`, `hpa.targetCPUUtilizationPercentage` | Autoscaling for every enabled agent, on CPU. Off by default. Do not enable it for michael while the job store is in memory. |
| Disruption budget | `pdb.enabled`, `pdb.minAvailable` | Off by default. With one replica and `minAvailable: 1`, the budget blocks node drains. |
| Sandbox deadline | `sandbox.activeDeadlineSeconds` | Hard stop for a sandbox pod. |

## Upgrade procedure

1. **Read the release notes** in `CHANGELOG.md`. Note any change to a configuration default or a removed key.
2. **Validate configuration against the new schema before you deploy.** The organisation file and every registry file must validate.
   `uv run squad config validate <file>` runs the schema from the checkout you deploy. A removed key fails here, not in production.
3. **Check the image for the target arch** (see below), then roll it out with the chart. Set the new tag in values, or use
   `scripts/bump_image.py --tag <tag>` on the chart checkout:

   ```bash
   helm upgrade code-squad deploy/helm/code-squad --namespace code-squad -f my-values.yaml --atomic --wait
   ```

   `--atomic` rolls back automatically when the new pods do not become ready.
4. **Verify.** `GET /ready` on every agent, then a dry-run review on one change request. Read the result's `stats.config_hash` and
   `warnings` for anything new.
5. **Watch** the invocation metrics for an hour (failure ratio, incomplete ratio, p95 latency) against the figures before the upgrade.

Configuration changes do not need an upgrade. The organisation file and the registry are hot-reloaded from their ConfigMaps. A broken
file keeps the last good configuration and raises `squad_config_reload_failures_total`.

Model and framework upgrades change behaviour. The decision record for the stack notes that the Strands hook and limit APIs are recent:
after upgrading the dependency, run the runtime tests (`just test tests/test_runtime.py`) and the eval replay (`just eval`) before the
rollout.

Asynchronous jobs in memory are lost when a pod restarts. A webhook-triggered review in progress at that moment is not re-run. The
next event for the change request (a new push, or a comment) starts a new run.

## Rollback

```bash
helm history code-squad --namespace code-squad
helm rollback code-squad <revision> --namespace code-squad --wait
```

The chart keeps five revisions (`revisionHistoryLimit: 5`). Images are tagged with the commit sha or the version, so a rollback returns to an identical
image. The ConfigMaps are rendered from `config.org` and `config.projects` in the values, so a rollback also restores the
configuration of that revision. Check those two values in the revision you return to.

## Images and architectures

- `deploy/Dockerfile` builds one image for every agent, from `python:3.12-slim`, with a non-root user (uid 10001). The sandbox image is
  built from `deploy/sandbox-node.Dockerfile` (uid 10002).
- The release build is multi-arch: `just build` runs `docker buildx build --platform linux/amd64,linux/arm64`. CI runs the same build.
- The local compose build is native (`docker compose build`), and the validation record notes that only amd64 was built locally, so an
  arm64 image has not been run by the validation. See [Local validation](local-validation.md).
- Pin the base image with `PYTHON_IMAGE` when your registry mirrors it.

## Capacity planning checklist

- [ ] Peak concurrent reviews, times the number of specialists per review, equals the gateway's concurrent request limit.
- [ ] Each concurrent pam run has room for a sandbox pod (CPU and memory from `sandbox.resources`).
- [ ] michael runs one replica, or the team has accepted the duplicate-run risk and tested the Redis path on the image.
- [ ] The advisory egress path is allowed for dwight, or the sources are switched off on purpose.
