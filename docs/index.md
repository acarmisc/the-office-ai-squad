# Code Squad

Code Squad is a set of specialised review and engineering agents for GitLab and GitHub
changes. It runs on any Kubernetes cluster, calls models only through a LiteLLM gateway, and
is configured, not coded, per project.

The squad reviews change requests (GitLab merge requests and GitHub pull requests), checks
security and pipeline risk, troubleshoots production symptoms in read-only mode, and can
implement a task in an isolated sandbox and open a change request for a human to review.
It never merges, and nothing in the squad changes a cluster.

## The six agents

Each agent is one container image started with a different `AGENT_NAME`. The ids are
character names from *The Office* (US), kept for discoverability. Documentation and outputs
use the functional role.

| Id | Role | What it does | Writes externally |
| --- | --- | --- | --- |
| `michael` | Orchestrator | Receives webhooks and requests, routes the change to specialists, merges their findings and publishes one consolidated review. | Summary note and commit status |
| `jim` | React reviewer | Reviews React and TypeScript changes. | Inline discussions and summary |
| `angela` | Java reviewer | Reviews Java and JVM changes, including Spring. | Inline discussions and summary |
| `dwight` | Security reviewer | Reviews code, configuration and dependencies, and checks live vulnerability data. | Inline discussions and summary |
| `darryl` | DevOps specialist | Reviews CI/CD, containers, IaC and Kubernetes manifests, and troubleshoots incidents with read-only access. | Review comments only |
| `pam` | Frontend engineer | Implements a task in a sandbox, runs the project's checks, pushes a branch and opens a change request. Advisor mode answers questions read-only. | Branch push and change request |

Every specialist can be called on its own. `michael` is the normal entry point for a change
request.

## What you get

- One consolidated review per change request, with a verdict (`approve`, `comment`,
  `request_changes` or `incomplete`) and a commit status `ai-review/<agent>`.
- A verdict that never says success when a specialist failed: the outcome is `incomplete`.
- Project rules as runtime skills, read from the target branch so a change cannot rewrite its
  own review rules.
- Configuration in layers (organisation, project registry, repository file, per call) with
  rules that stop a repository from loosening the platform's settings.
- Dry-run as a first-class mode: `post: false` runs everything and performs no external write.

## Quick start (about 10 minutes, offline)

The quick start runs the six agents in Docker Compose against an offline fake LLM. No API key
and no VCS account are needed. It proves that the images start, the HTTP contract works and
dry-run performs no writes.

Prerequisites: Docker with Compose v2, and a checkout of this repository.

1. Build the image and start the stack. Compose builds `code-squad:dev` from
   `deploy/Dockerfile` and starts `fake-llm` plus one container per agent.

   ```bash
   docker compose -f deploy/compose.yaml up -d --build
   ```

2. Run the HTTP smoke test. It waits for each agent's `/ready` and sends one dry-run
   invocation to each agent. It exits 1 when any agent fails.

   ```bash
   scripts/smoke_test.sh compose
   # or, through the task runner:
   just compose-smoke
   ```

3. Send an invocation yourself to michael (port 8081 on the host):

   ```bash
   curl -sS -X POST http://localhost:8081/invocations \
     -H 'content-type: application/json' \
     -d '{"prompt": "smoke test", "post": false}'
   ```

   The response is an `InvocationResult` JSON document with `status`, `verdict`, `summary`,
   `findings` and `stats`. `posted` is zero because `post` is `false`.

4. Stop the stack:

   ```bash
   docker compose -f deploy/compose.yaml down
   ```

The compose agents listen on `127.0.0.1` ports 8081 (michael) to 8086 (pam). The fake LLM is
not published to the host. Behind a TLS-intercepting proxy, see [Local environments](deployment/local.md)
for the base-image step.

## Where to go next

| You are | Start with |
| --- | --- |
| Deciding whether to adopt it | [Architecture overview](architecture/overview.md), [Security threat model](security/threat-model.md) |
| Onboarding a project | [New project checklist](onboarding/new-project.md) |
| Configuring behaviour | [Configuration concepts](configuration/concepts.md), [Recipes](configuration/recipes.md), [Configuration reference](reference/configuration.md) |
| Installing on Kubernetes | [Helm values](deployment/helm.md), [Secrets](deployment/secrets.md), [Network and egress](deployment/network-and-egress.md) |
| Connecting GitLab or GitHub | [GitLab](vcs/gitlab.md), [GitHub](vcs/github.md) |
| Running it | [Operations runbook](operations/runbook.md), [FAQ](faq.md) |
| Changing the code | [Contributing](contributing/index.md), [Testing](testing/index.md), [Decisions](decisions/index.md) |
| Picking up the project cold | [Handoff](HANDOFF.md), [Build brief](BRIEF.md) |
