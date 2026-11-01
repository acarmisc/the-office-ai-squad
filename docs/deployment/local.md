# Local environments

Three ways to run the squad on a workstation, from the lightest to the closest to production: a single agent process, Docker Compose
with all six agents, and a kind cluster with the Helm chart. Each one uses the offline fake LLM unless you point it at a gateway. None of
them talks to a real VCS host unless you configure one.

The record of what was run and what failed in the last validation of these artifacts is
[Local validation of the deployment artifacts](local-validation.md).

## One agent, no containers

Requires `uv` and Python 3.12. `just invoke` also needs `jq`. For a shorter route that needs only `uv`, see
[Local demo](../getting-started/local-demo.md).

```bash
uv sync
# Terminal 1: the offline fake LLM on port 4000
PORT=4000 uv run python -m deploy.fake_llm
# Terminal 2: michael on port 8080
LLM_BASE_URL=http://localhost:4000/v1 LLM_API_KEY=fake-key-for-local-demo \
  SQUAD_ALLOW_UNAUTHENTICATED=1 just run-local michael

# Terminal 3: a dry-run invocation
just invoke michael "smoke test"
```

`just run-local <agent>` starts uvicorn with `AGENT_NAME` set. `just invoke <agent> "<prompt>" [url]` sends a dry-run request
(`post: false`) to `/invocations`. Use `curl http://localhost:8080/ready` to confirm the agent loaded.

Without a token, `/invocations` refuses every request, so local runs set `SQUAD_ALLOW_UNAUTHENTICATED=1`. To test the token
path instead, set `SQUAD_API_TOKEN` in both the server and the shell: `just invoke` then sends it as a bearer header.

Without `LLM_BASE_URL`, the agent calls `http://localhost:4000/v1`. Without `LLM_API_KEY` or `LLM_API_KEY_FILE`, a model call fails with
a clear configuration error, and the run is `failed`.

## Docker Compose: six agents and the fake LLM

Requires Docker with Compose v2.

```bash
docker compose -f deploy/compose.yaml up -d --build
scripts/smoke_test.sh compose        # or: just compose-smoke
docker compose -f deploy/compose.yaml down
```

The file `deploy/compose.yaml` starts `fake-llm` and one container per agent from the `code-squad:dev` image. The agents are on
`127.0.0.1` at ports 8081 (michael) to 8086 (pam). `fake-llm` is not published to the host. Each container runs read-only, as uid
10001, with no capabilities and `no-new-privileges`. michael is given the specialist URLs of the other containers.

The smoke test waits for each agent's `/ready`, sends a dry-run invocation to each, and checks that each answers `complete` with
nothing posted. It exits 1 when any agent fails.

### Behind a TLS-intercepting proxy

A corporate proxy that re-signs HTTPS breaks the image build because the base image does not trust the proxy's root. Build a base
image that trusts it, and pass it with `PYTHON_IMAGE`:

```bash
sed -n "1,25p" scripts/local_ca_base.sh   # read the header first; it is for local verification only
PYTHON_IMAGE=<your trusted base image> docker compose -f deploy/compose.yaml up -d --build
```

The script's header describes what it trusts and where the certificate comes from. Do not use the derived base outside your
workstation.

## kind with the Helm chart

Requires `kind`, `kubectl`, `helm`, Docker and, for the smoke test, `kubeconform` when you lint.

```bash
just kind-up        # creates the cluster, builds and loads the image, deploys the fake LLM, installs the chart
just kind-smoke     # port-forwards each agent and runs scripts/smoke_test.sh k8s
```

`kind-up.sh` installs the chart with `deploy/helm/code-squad/values-examples/minimal-kind.yaml`. That file disables the NetworkPolicies
and the sandbox, because kind's default CNI does not enforce policies and the sandbox namespace does not exist. Consequences:

- The policies are not tested by the kind demo. Test them on a cluster whose CNI enforces NetworkPolicy.
- With the sandbox off, pam runs its checks through the local process sandbox inside its own container. This is acceptable for a
  disposable demo cluster and not for anything else. See [pam](../agents/pam.md).

The validation record notes that cluster creation can fail in some environments (for example with a kubeadm error on a constrained
host); see [Local validation](local-validation.md).

## Tests and checks on a workstation

```bash
uv sync
just check          # the whole gate, which needs helm and kubeconform for the chart step
just test tests/michael   # one area
```

`just check` runs the same steps as CI. Run `just docs` after documentation changes, because the build is strict and fails on any
broken link.

## Clean up

```bash
docker compose -f deploy/compose.yaml down -v
kind delete cluster --name code-squad
```
