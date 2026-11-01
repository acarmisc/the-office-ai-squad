# Request lifecycle inside one agent

This page follows one `POST /invocations` through a single agent process: from validation to the result. It applies to every agent.
`michael` adds a fan-out step in front of this path (see [review sequence](review-sequence.md)), and its specialists then run this same
path with `post: false`.

## The path

```mermaid
flowchart TD
  REQ["POST /invocations"] --> AUTH{"bearer token ok?"}
  AUTH -- no --> R401["401"]
  AUTH -- yes --> SIZE{"body within limit?"}
  SIZE -- no --> R413["413"]
  SIZE -- yes --> VAL["validate_invocation: strict schema, org-only keys, token-shaped values"]
  VAL -- errors --> R422["422 with the list of errors"]
  VAL -- ok --> IDEM{"idempotency key seen?"}
  IDEM -- finished --> REPLAY["stored result"]
  IDEM -- running --> R409["409 in flight"]
  IDEM -- new --> SVC["build services per call: effective config, VCS provider, secrets, skills, knowledge"]
  SVC --> ALLOW{"model in allow-list?"}
  ALLOW -- no --> R422B["422 model not allowed"]
  ALLOW -- yes --> PLAN{"agent enabled for this call?"}
  PLAN -- no --> DIS["incomplete result, model never called"]
  PLAN -- yes --> RUN["run_task: runtime loop"]

  subgraph LOOP["runtime loop (one retry at most)"]
    direction TB
    TURN["model turn"] --> TOOL{"tool call?"}
    TOOL -- yes --> POL["policy hook: tool classified? READ, LOCAL_MUTATION or EXTERNAL_WRITE; gate allows?"]
    POL -- refused --> NOTE["refusal returned to the model; dry run counted"]
    POL -- allowed --> EXEC["run the tool; untrusted output wrapped"]
    EXEC --> TURN
    NOTE --> TURN
    TOOL -- no --> STOP{"finish called?"}
    STOP -- no --> LIM["budget or turn limit, or end of turn"]
    STOP -- yes --> FIN["finish: validate verdict and findings, reject twice means no result"]
    LIM --> RETRY{"truncated or overloaded and fallback set?"}
    RETRY -- yes --> TURN
  end

  RUN --> LOOP
  FIN --> GUARD["result guards: for example dwight offline verdict, accepted risks"]
  LIM --> GUARD
  GUARD --> PUB["findings: anchor, dedupe, verdict. Publish only if the gate allows"]
  PUB --> RES["InvocationResult: status, verdict, findings, warnings, stats, posted"]
  RES --> OBS["metrics, JSON log line, stored under the idempotency key"]
  OBS --> OUT["200 or 202 job"]
```

## What each stage guarantees

| Stage | Where it lives | Guarantee |
| --- | --- | --- |
| Auth and size | `server.py` (`_authorized`, `_json_body`) | Refused before any parsing or model work. |
| Validation | `_common/validation.py` | Unknown keys and organisation-only keys are refused. Caller tags in reserved namespaces are dropped. |
| Idempotency | `server.py` (`_claim_key`, `InFlightRegistry`) | The same key gives the stored result, never a second run. |
| Services | `_common/services.py` (`ServiceBuilder`) | Built per call, so configuration changes apply without a restart. Secrets are resolved here, not in the agent prompt. |
| Allow-list and plan | `validation.model_allowlist_errors`, `services.plan_run` | A disallowed model or a disabled agent never reaches the model. |
| Runtime loop | `_common/runtime.py` (`run_task`, `_run`, `_attempt`) | Turn, token and wall-clock budgets. One retry on truncation or gateway overload, with `fallback_model`. |
| Policy hook | `_common/policy_hook.py`, `_common/tool_policy.py` | Every tool is classified. Under dry run the external-write gate refuses and records the attempt. |
| Finish | `runtime._finalize` | A run without a valid `finish` is `incomplete`, never `complete`. |
| Guards | `runtime._guarded` | Agent-specific checks run last on the finished result, in the order the services list them. |
| Publication | `_common/findings.py`, `_common/posting.py` | One pipeline. Writes only when `post` is true and no organisation override forces dry run. |

## Reading a result

- `status` says whether the run finished (`complete`), finished without a verdict (`incomplete`) or raised (`failed`).
- `warnings` explains every degraded or refused step in one line each. It is the first place to look.
- `stats` holds the iteration count, token counts and the `config_hash` that produced the run.
- `posted` counts what was written. In dry run it is zero.

## Where to add code on this path

| You want to | Change |
| --- | --- |
| Accept a new request field | `_common/contract.py` and the schema in `schemas/`; regenerate with `just docs-gen` |
| Add a service (for example a new client) | `_common/services.py`, built from configuration |
| Add a tool | [Your first change](../contributing/first-change.md#example-2-add-a-read-only-tool) |
| Change how a verdict is computed | `_common/findings.py`, with a test that fails on the old behaviour |
