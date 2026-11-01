# Contributing to Code Squad

Thank you for helping. This file is the short version. The full guide is in the documentation:
[Contributing](docs/contributing/index.md), with the [architecture tour](docs/contributing/tour.md) and
[your first change](docs/contributing/first-change.md).

## Set up

You need Python 3.12 or later and [uv](https://docs.astral.sh/uv/). Everything else is optional:

| Tool | Needed for | Without it |
| --- | --- | --- |
| `just` | The task recipes (`just check`) | Run the commands listed in `justfile` by hand |
| `helm` and `kubeconform` | The chart checks (`just helm-lint`) | The chart step fails locally; CI still runs it |
| Docker with Compose v2 | The six-agent demo and the smoke test | Use the single-agent route in [Running and debugging](docs/contributing/running-and-debugging.md) |
| `jq` | `just invoke` | Use `curl` directly |

```bash
git clone https://github.com/acarmisc/the-office-ai-squad.git
cd the-office-ai-squad
uv sync
just check
```

## The gate

`just check` is the gate. It runs ruff (lint and format), mypy in strict mode, pytest, the prompt checks, the generated-docs drift
check, a strict documentation build, the Helm lint and the secret scan. CI runs the same steps. A red gate is not reviewed, and you
should never leave the tree broken.

Run the part you are working on while you iterate, for example `just test tests/michael`, and the whole gate before you push.

## Conventions

The conventions are in [AGENTS.md](AGENTS.md). In short:

- Python 3.12, `uv` with `uv.lock`, short functions, explicit types, `Enum` or `Literal` instead of boolean flags.
- Comments only where they explain a non-obvious *why*.
- No secrets, tokens or real hosts in code, tests, fixtures or docs. Use obvious fakes such as `fake-token-for-tests`.
- Tests do not use the network.
- Every tool is classified in `src/code_squad/_common/tool_policy.py`. Every external write is gated.

## How the tests are organised

- **Fake model.** `ScriptedModel` in `src/code_squad/_common/fake_model.py` replays a list of turns. Tests use it instead of a real
  model, so a run is deterministic.
- **Fake VCS.** `FakeVcsProvider` in `src/code_squad/_common/vcs/fake.py` is an in-memory host that records every write. Assert that a
  dry run leaves `fake.writes` empty.
- **Recorded HTTP.** GitLab and GitHub are tested with `respx` against recorded responses, with unexpected requests failing the test.
- **Conformance.** One suite in `src/code_squad/_common/vcs/conformance/` runs on the fake, GitLab and GitHub. A new provider must pass
  it.
- **Security tests test the refusal.** For a tool, a configuration key or a dry run, test that the forbidden thing does not happen.

Details: [Testing](docs/testing/index.md).

## Adding an agent, a tool or a provider

- **Agent.** A platform change that needs an ADR first. See [Adding an agent](docs/contributing/index.md#adding-an-agent).
- **Tool.** Classify it in `tool_policy.py`, add it to one agent's `SPEC.tools`, and test the classification and the refusal. See
  [Your first change](docs/contributing/first-change.md#example-2-add-a-read-only-tool).
- **VCS provider.** Implement the protocol and pass the conformance suite. See [Adding a provider](docs/vcs/adding-a-provider.md).
- **Knowledge.** A topic in a pack needs no code. See [Knowledge packs](docs/onboarding/knowledge-packs.md).

## Commits

Use conventional commits in the imperative mood, one logical change per commit:

```text
feat(jim): add count_lines read tool
fix(publish): keep inline comments on added lines only
docs(deploy): correct the minimal values file
```

Add an entry under `## Unreleased` in [CHANGELOG.md](CHANGELOG.md) for anything a user or an operator would notice.

## Pull requests

1. Branch from `main`. Keep the change focused.
2. Fill in the [pull request template](.github/pull_request_template.md). It lists the checks that reviewers look for.
3. Add a regression test for each bug, and a refusal test for each security-relevant change.
4. Update the generated reference pages (`just docs-gen`) when you change a schema, a tool or a configuration key.
5. Make sure the gate is green. Then request a review.

## Decisions (ADRs)

Record a non-trivial choice as an ADR in `docs/decisions/NNNN-title.md`, numbered in sequence, and add it to the
[decisions index](docs/decisions/index.md). Do not change an accepted decision silently: write a new ADR that supersedes it. See
[ADR process](docs/contributing/index.md#adr-process).

## Security

Do not report a vulnerability in a public issue or pull request. Follow [SECURITY.md](SECURITY.md).

## Behaviour

Everyone who takes part in this project agrees to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Where to ask

- A bug in the code or the docs: open an issue with the bug report template.
- An idea or a change in behaviour: open an issue with the feature request template, before a large pull request.
- A question about deploying or using the squad: read the [troubleshooting guide](docs/getting-started/troubleshooting.md) first, then
  open an issue.
