# 0014 — GitHub Actions review in the job

- Status: accepted
- Date: 2026-11-01

## Context

A frontend team wants a `jim` review of each pull request without running a cluster, a webhook
and a secret store first. The deployed service remains the right tool for several agents, `pam`
and shared operation. The in-runner mode must reuse the same review, publication and gate as the
service, so that a dry-run review means the same thing in both places.

## Decision

- **One execution path.** The invocation steps (validate, build services, check the model
  allow-list, apply the agent configuration, run) live in `_common/execute.py`. The HTTP server,
  `squad invoke` and `squad ci review` all use them. The server splits the steps because it answers
  422 before it claims an idempotency key and runs michael in the background.
- **In-process context.** `squad ci review` reads the pull request from `GITHUB_EVENT_PATH`. It
  builds the services through the single-project bootstrap (`VCS_PROVIDER=github`,
  `VCS_BASE_URL=$GITHUB_API_URL`, `VCS_TOKEN=$GITHUB_TOKEN`) using an explicit environment mapping,
  not a change to `os.environ`. No HTTP and no API token are involved.
- **A composite action, not a Docker action.** The image runs as uid 10001 and cannot write the
  runner's `GITHUB_OUTPUT` and `GITHUB_STEP_SUMMARY`. The action runs the image with `docker run`
  as the job's user, with a read-only root filesystem, and writes the outputs and the summary in a
  step of its own that runs `if: always()`.
- **Secrets by name.** `GITHUB_TOKEN` and `LLM_API_KEY` reach the container as environment
  variables named on the `docker run` command line (`-e NAME`), never as values in arguments or in a
  `run:` script.
- **No code from the pull request.** The action never checks out the repository. The workspace holds
  only what the workflow put there, so `--skills-path` reads trusted content by construction.
- **Safe defaults.** A dry run unless `post` is `true`. A draft pull request is skipped. A fork
  pull request without `LLM_API_KEY` is skipped, because forks get no secrets. Only `pull_request`
  is used in the example; `pull_request_target` is accepted by the CLI and not recommended.
- **Gate.** `fail-on` is `none` by default, so the check is advisory until the team opts in. A
  failed run always exits 1.
- **michael in process.** `InProcessSpecialistClient` runs the specialists through the same
  execution path, with `post` forced to false, and michael publishes once. The fan-out keeps its
  timeouts. The HTTP circuit breakers do not apply, and a specialist that overruns keeps running
  until the job ends.
- **Release coupling.** `bump_image.py --version` sets the composite action's image default, and the
  release `verify` job checks it against the tag, so the action never runs an image older than its
  own release.

## Consequences

- Each run pays for runner minutes and has no state across runs. Webhooks, metrics, `pam` and the
  specialist service are out of scope for this mode.
- The composite action's shell is the only place where result text is turned into a summary. It
  escapes table cells and accepts only enumerated tokens as outputs; a test executes that script.
- Another agent for the same repository is another step. Each step posts its own
  `ai-review/<agent>` status, so the outputs do not collide.
- A new agent or a new output field needs a change in the result contract and in the summary
  script, and both are covered by tests.
