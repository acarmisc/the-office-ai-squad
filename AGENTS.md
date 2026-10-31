# AGENTS.md — conventions for humans and coding agents

Read `docs/BRIEF.md` (the build brief) and `STATUS.md` (current state) first.

## Toolchain

- Python ≥ 3.12, `uv` + `uv.lock`, `hatchling`, `src/` layout.
- `just check` is the gate: ruff (lint + format), mypy `--strict`, pytest, prompt checks,
  generated-docs drift, `mkdocs build --strict`, helm lint + kubeconform, secret scan.
- Never leave the tree broken; commit at the end of each milestone with conventional
  commits (`feat(scope): ...`, imperative mood).

## Code

- Short functions, explicit types everywhere, `Enum`/`Literal` instead of boolean flags.
- Private by default (`_name`); frozen dataclasses or pydantic models for data.
- No comments unless they explain a non-obvious *why*.
- Never invent library APIs: inspect the installed package (`uv run python -c "help(...)"`).
- No secrets in code, tests, fixtures, logs or docs; use obvious fakes
  (`fake-token-for-tests`).
- No network in tests: use `respx`, the fake VCS provider, the scripted fake model.

## Agents

| id | role |
|---|---|
| `michael` | orchestrator |
| `jim` | React reviewer |
| `angela` | Java reviewer |
| `dwight` | security reviewer |
| `darryl` | DevOps specialist |
| `pam` | senior frontend engineer |

Agent ids are lowercase single tokens; the mapping lives in
`src/code_squad/_common/registry.py`. Personas are names only: prompts and outputs stay
professional.

## Security invariants (tests must keep these green)

- Every tool is classified in `_common/tool_policy.py` (`READ`, `LOCAL_MUTATION`,
  `EXTERNAL_WRITE`).
- `post: false` disables every `EXTERNAL_WRITE` tool (`DryRunError`).
- Untrusted content (diffs, issues, logs, skills, advisories) is wrapped by
  `_common/untrusted.py` and never treated as instructions.
- The squad never merges, never mutates clusters, never executes fork code.

## Decisions

Record non-trivial choices as ADRs in `docs/decisions/NNNN-title.md`.
