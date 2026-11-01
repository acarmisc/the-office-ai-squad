# Code Squad

Specialised review and engineering agents for GitLab and GitHub changes, portable to any Kubernetes cluster.

Six agents, one image: `michael` (orchestrator), `jim` (React reviewer), `angela` (Java reviewer), `dwight` (security reviewer),
`darryl` (DevOps, read-only), and `pam` (frontend engineer, implements tasks in a sandbox and opens a change request). The squad
never merges and never changes a cluster. Configuration, not code, sets each project's behaviour.

## Quick start (offline, about 10 minutes)

```bash
docker compose -f deploy/compose.yaml up -d --build
scripts/smoke_test.sh compose
docker compose -f deploy/compose.yaml down
```

The agents then listen on `127.0.0.1:8081` (michael) to `8086` (pam), with an offline fake LLM. Full steps and the kind path are in
[docs/index.md](docs/index.md) and [docs/deployment/local.md](docs/deployment/local.md).

## Documentation

- [Overview and quick start](docs/index.md)
- [Architecture](docs/architecture/overview.md) and [HTTP contract](docs/architecture/contract.md)
- [Agents](docs/agents/michael.md), [configuration](docs/configuration/concepts.md) and [recipes](docs/configuration/recipes.md)
- [GitLab](docs/vcs/gitlab.md) and [GitHub](docs/vcs/github.md) setup, [new project checklist](docs/onboarding/new-project.md)
- [Helm chart](docs/deployment/helm.md), [secrets](docs/deployment/secrets.md), [network and egress](docs/deployment/network-and-egress.md)
- [Runbook](docs/operations/runbook.md), [threat model](docs/security/threat-model.md), [hardening checklist](docs/security/hardening.md)
- [Decisions](docs/decisions/index.md), [FAQ](docs/faq.md), [handoff](docs/HANDOFF.md), [changelog](CHANGELOG.md)

## Development

```bash
uv sync
just check      # ruff, mypy --strict, pytest, prompt checks, docs drift, mkdocs --strict, helm lint, secret scan
just eval       # offline replay of the evaluation cases
```

Read [AGENTS.md](AGENTS.md), [STATUS.md](STATUS.md) and [the build brief](docs/BRIEF.md) before you change the code.

## Notes for operators

- The GitHub App manifest in `examples/github/github-app-manifest.json` requests `contents: write`. That permission is needed only
  when `pam` is deployed and used. Lower it to `read` otherwise.
- `/invocations` is not authenticated by the application. Keep it inside the cluster network, or put an authenticating layer in front
  of it. See [ingress and webhooks](docs/deployment/ingress-webhooks.md).
