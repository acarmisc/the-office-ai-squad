# Contributing

This page covers the working rules of the repository and the four changes a contributor usually makes: an agent, a tool, a
VCS provider and a knowledge pack. It also covers the decision record process and releases. The agent-level conventions are in
`AGENTS.md` at the repository root; this page expands them.

## Working rules

- Read `docs/BRIEF.md` (the build brief), `STATUS.md` (current state) and `AGENTS.md` before a change.
- Run `just check` before a commit. The gate must be green; never leave the tree broken.
- Commit at the end of a milestone or a complete change, with conventional commit messages (`feat(scope): ...`,
  `fix(scope): ...`, `docs(scope): ...`) in the imperative mood.
- Python 3.12 or later, `uv` with `uv.lock`, `hatchling` and the `src/` layout. Do not add a dependency without a reason
  recorded in an ADR when it changes the platform.
- Code: short functions, explicit types everywhere (`mypy --strict`), `Enum` or `Literal` instead of boolean flags, private
  names by default (`_name`), frozen dataclasses or pydantic models for data.
- Comments only where they explain a non-obvious *why*. Do not document what the code says.
- Never invent a library API. Inspect the installed package before you call it.
- No secrets in code, tests, fixtures, logs or docs. Use obvious fakes such as `fake-token-for-tests`. The secret scan blocks
  token-shaped strings.
- Tests do not use the network. Use `respx`, the fake VCS provider and the scripted model.
- Security-relevant behaviour (tool policy, dry run, untrusted content, input validation) needs a test first, and the test must
  check the refusal.

## Repository layout

| Path | Content |
| --- | --- |
| `src/code_squad/_common/` | Platform: contract, runtime, policy, configuration, VCS providers, skills, sandbox, services, observability |
| `src/code_squad/<id>/` | One package per built-in agent: `__init__.py` (the `SPEC`), `prompt.md`, `knowledge/` and any tools |
| `src/code_squad/server.py` | HTTP application factory |
| `deploy/` | Dockerfiles, Helm chart, compose, kind scripts, fake LLM, observability and secret examples |
| `schemas/` | Generated JSON Schemas (`scripts/gen_schemas.py`) |
| `examples/` | Organisation, repository, GitLab and GitHub examples |
| `eval/` | Golden cases, fixtures, replays, scorers, runner |
| `docs/` | Documentation (this site), generated reference pages, decision records |
| `scripts/` | Generators, checks, the smoke test and the image bump script |

## Adding an agent

Built-in agents are a platform change, not a configuration change. The six ids are fixed in `_common/registry.py`. To add a seventh
built-in agent:

1. Decide the role, the modes, the tools and the policy class of each tool. Write an ADR first.
2. Create `src/code_squad/<id>/` with `__init__.py` exposing `SPEC` (an `AgentSpec`), `prompt.md` and a `knowledge/` directory with
   an index topic. Follow an existing package: `jim` for a reviewer, `pam` for an implementer.
3. Add the id to `AGENT_IDS` and `ROLES` in `_common/registry.py`, and to the `Literal`s or lists in `_common/config/schema.py` that enumerate the built-in agents.
4. Write the prompt with the required sections (`## Role and boundaries`, `## Untrusted content`, `## Method`, `## Severity rubric`,
   `## Output contract`, `## Dry-run`, `## Tools and skills`, `## Limits`), under 2500 words. `just prompts` checks this.
5. Add the agent to the chart (`agents.<id>` in `values.yaml`, the schema, and the templates that list agents), to `deploy/compose.yaml`,
   to `scripts/smoke_test.sh` and to `catalog-info.yaml`, which needs one Component and one API for it.
6. Add tests: the registry test, a scripted run, the policy test that the tools are classified, and the catalogue test.
7. Regenerate the reference pages with `just docs-gen` and update the agent's documentation page and the navigation.

Extra agents (declared in configuration) need none of this; see [Extra agents](../agents/extra-agents.md).

## Adding a tool and classifying it

Every tool an agent can call must be classified in `_common/tool_policy.py`:

| Class | Meaning | Where it can run |
| --- | --- | --- |
| `READ` | Changes nothing | Any agent |
| `LOCAL_MUTATION` | Changes only the sandbox working copy | pam only |
| `EXTERNAL_WRITE` | Changes a remote system | Only the gated tools (`publish_review`, `push_branch`, `open_change_request`) |

Steps:

1. Write the tool as a Strands tool in the agent's package or in `_common/`. Use an explicit signature and a docstring that the model
   reads as its instructions.
2. Add the name to `TOOL_POLICY` with its class. An unclassified name is refused at run time, and a test fails.
3. If it is an external write, call `ctx.gate.require_write(name)` inside the tool body, as well as the policy hook's check. Both
   checks are required.
4. Add the tool to the agent's `SPEC.tools` only. A preset for extra agents is a separate list in `_common/config/presets.py`; a
   preset may contain `publish_review` as its only external write.
5. Add tests: classification, refusal under dry run, and the result shape. Regenerate `reference/tool-policy.md` with `just docs-gen`.

Do not add a tool that changes a cluster. A darryl test scans the source for mutation calls, and the decision record
[ADR 0006](../decisions/0006-darryl-read-only.md) explains why.

## Adding a VCS provider

Follow [Adding a VCS provider](../vcs/adding-a-provider.md). The provider must pass the conformance suite for the fake and the existing
hosts before it is merged.

## Adding a knowledge pack

Follow [Knowledge packs](../onboarding/knowledge-packs.md). A topic that changes review behaviour needs an eval case.

## ADR process

Record a non-trivial choice as an ADR in `docs/decisions/NNNN-title.md`, numbered in sequence. Use the existing files as the form:

- A title line with the number and the decision.
- `Status` (proposed, accepted, superseded by NNNN) and `Date`.
- `Context`: the problem and the constraints, with the brief's section where relevant.
- `Decision`: what was chosen, precisely, with the names of the modules that implement it.
- `Alternatives considered`, when there were real alternatives.
- `Consequences`: what is now true, what is harder, and the open points for review.

An ADR does not change an accepted decision silently. Write a new ADR that supersedes it, and update the old one's status line. The
[decisions index](../decisions/index.md) lists every ADR; add the new one there.

## Release and versioning

- **Versions.** The package version is in `pyproject.toml` and `src/code_squad/__init__.py`. The chart has `version` and `appVersion`
  in `deploy/helm/code-squad/Chart.yaml`. Keep the application version and `appVersion` equal for a release.
- **Image tags.** The default image tag is the short commit sha, and a release also gets its semantic version.
- **Bumping.** `scripts/bump_image.py` sets `version` and `appVersion` in `Chart.yaml` and `image.tag` in `values.yaml`:

  ```bash
  uv run python scripts/bump_image.py --version 0.2.0 --tag 0.2.0 --dry-run
  uv run python scripts/bump_image.py --version 0.2.0 --tag 0.2.0
  ```

  The script edits lines, so the comments in both files survive. `--dry-run` prints the diff and writes nothing.
- **Changelog.** Add an entry to `CHANGELOG.md` under the new version, with the user-visible changes and any change of behaviour or
  configuration default.
- **Checks before a release.** `just check` green; the Docker build for both architectures (`just build`, which uses buildx); the Helm
  lint for the default and example values; the smoke test on compose; a dry-run review on a test change request.
- **Tag and publish.** Tag the commit, push the image, and update the chart version in the deployment repository. The CI deploy job is
  manual and only prints the command today.

## Documentation

The documentation is built with `mkdocs build --strict`, so every link must resolve and every page must be in the navigation.
Generated reference pages must not be edited by hand; run `just docs-gen`. Validated blocks must stay valid: `just test tests/test_docs_examples.py`.
