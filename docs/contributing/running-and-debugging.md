# Running and debugging

This page shows how to run one agent on your workstation against the offline fake model, how to send it a request, and where to look
when something behaves unexpectedly.

## Run one agent

```bash
uv sync
PORT=4000 uv run python -m deploy.fake_llm &          # the offline model, port 4000
LLM_BASE_URL=http://localhost:4000/v1 LLM_API_KEY=fake-key-for-local-demo \
  SQUAD_ALLOW_UNAUTHENTICATED=1 AGENT_NAME=jim \
  uv run uvicorn code_squad.server:app --port 8080
```

`just run-local jim` runs the last command with the same `AGENT_NAME`. `SQUAD_ALLOW_UNAUTHENTICATED=1` opens the API for this local run only.
Confirm it is ready:

```bash
curl -sS localhost:8080/ready
```

Send a dry-run request. `just invoke` is a shorthand for the same call; it needs `jq`:

```bash
curl -sS -X POST localhost:8080/invocations -H 'content-type: application/json' \
  -d '{"prompt": "smoke test", "post": false}' | jq '{status, verdict, warnings, stats}'
```

The fake LLM replays the script in `deploy/fake_llm/scripts/<agent>.json`. A reply therefore depends on the script, not on the prompt. To
test a real path, write a `ScriptedModel` in a test instead (see [testing](../testing/index.md#the-fake-model)).

## Run a review in one process

For a review with a fake VCS and the scripted model, without a server, use the demo module. It is the same wiring the tests use:

```bash
uv run python -m scripts.demo_review
```

Read `scripts/demo_review.py` as a template. It builds a `FakeVcsProvider`, a `ScriptedModel` with the turns you want, and calls
`create_app` with `TestClient`. Copy it into a scratch file for an experiment and delete the copy afterwards.

## Run the CLI

The `squad` command is the same code as the server, without HTTP:

```bash
uv run squad invoke jim "smoke test" --no-post
uv run squad config validate examples/org examples/repo
uv run squad config explain acme/web-shop --org examples/org/squad.yaml --projects examples/org/projects.yaml
```

`squad invoke` uses the real model factory, so it needs `LLM_BASE_URL` and a key. Without them it fails with a configuration error,
which is the expected result.

## Debugging checklist

| Symptom while developing | What to check |
| --- | --- |
| `/invocations` returns `401` | `SQUAD_API_TOKEN` is set in the server environment and in the request header, or `SQUAD_ALLOW_UNAUTHENTICATED=1` is set for local runs. |
| The model is never called, the result is `incomplete` | The agent is disabled for this call (`agents.<id>.enabled`), or the plan refused the run. Read `warnings`. |
| A tool is refused | The name is missing from `TOOL_POLICY`, or it is an external write under dry run. The refusal is recorded in `warnings`. |
| The verdict is `incomplete` in a test | `finish` was not called, or it was rejected twice. Assert on `warnings`; the reason is named there. |
| A config key has no effect | Its layer lost to a later one, or a repository layer was rejected as a whole. Run `squad config explain --repo-config`. |
| A VCS call behaves differently from the fake | The fake is not the real host. Add a case to the conformance suite, and record the response for the recorded-HTTP tests. |

## Logs, traces and metrics

- Logs are JSON lines on stderr. Set `LOG_LEVEL=DEBUG` for a short investigation only. Look for `invocation finished` with the
  `invocation_id`.
- `/metrics` exposes the counters in the [runbook](../operations/runbook.md#metrics-glossary).
- Traces go to an OTLP collector when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Without it, the service runs without traces.

## Stop everything

```bash
pkill -f "deploy.fake_llm"; pkill -f "uvicorn code_squad.server"
```

Use `docker compose -f deploy/compose.yaml down -v` for the compose stack.
