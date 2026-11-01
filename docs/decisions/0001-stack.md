# 0001 — Stack: Strands Agents + FastAPI, uv, Python 3.12

- Status: accepted
- Date: 2026-10-31

## Context

The reference squad runs on AWS Strands Agents behind Bedrock AgentCore. This project
must run on any Kubernetes cluster, stay runnable on AgentCore (same HTTP contract) and
talk to models only through a LiteLLM gateway.

## Decision

- Agent loop: **Strands Agents SDK** (`strands-agents`, pinned in `uv.lock`; 1.63 at
  bootstrap) with its OpenAI-compatible model (`strands.models.openai.OpenAIModel`)
  pointed at the LiteLLM gateway. Provider code is imported only in
  `code_squad/_common/model.py`.
- Iteration limits use Strands request `limits={"turns": N}`; a run that stops with
  `stop_reason="limit_turns"` is reported as `incomplete`.
- Tool policy and dry-run are enforced twice: a Strands `BeforeToolCallEvent` hook
  cancels unclassified or gated tools, and every `EXTERNAL_WRITE` tool also calls the
  posting gate itself (defence in depth).
- HTTP: **FastAPI + uvicorn**, port 8080, `POST /invocations`, `GET /ping`.
- Tooling: `uv` + `uv.lock`, `hatchling`, `src/` layout, ruff, mypy `--strict`, pytest,
  `just` as the task runner, mkdocs-material for TechDocs.
- The local interpreter used for development is the one pinned by `.python-version`
  (3.12); the container uses `python:3.12-slim`.

## Consequences

- A new Strands `Agent` is created per invocation (agents hold conversation state).
- Tests use a scripted fake `Model` implementation; no network in the default gate.
- Upgrading Strands requires re-running the runtime tests, as hook and limit APIs are
  relatively recent.
