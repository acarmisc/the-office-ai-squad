# 0002 — Runtime semantics: retries, dry-run and payload strictness

- Status: accepted
- Date: 2026-10-31

## Context

The brief requires validated output through `finish()`, one retry on truncation, an
`incomplete` result on the iteration limit, and a dry-run gate. Strands 1.63 raises
`MaxTokensReachedException` on truncation and propagates model errors unchanged.

## Decision

- At most **one** retry per invocation (two attempts in total). Truncation retries with
  `retry_model_id` when set, otherwise the same model. A run that ends without `finish()`
  gets one retry asking for `finish()`.
- `finish()` with invalid arguments returns the validation error to the model; a
  second invalid call stops the run as `incomplete`.
- `finish()` cannot return the verdict `incomplete`; only the runtime sets it.
- `stop_reason == "limit_turns"` yields `status=incomplete`, `verdict=incomplete`.
- A model exception yields `status=failed`; only the exception type is reported.
- `post` must be a real boolean when present; `null` is rejected (fail closed).
  Absent `post` allows writes (`POST_WHEN_ABSENT = True`).
- The model factory signature is `(model_id, max_tokens, temperature, tags)` so LiteLLM
  tags reach the gateway (`extra_body.metadata.tags`).
- Unclassified tool names are refused and never become metric labels.
- Async jobs (`Prefer: respond-async`) use the in-memory session store by default, so a
  job id is only visible on the replica that accepted it; set `SESSION_STORE_URL` to a
  Redis URL for multi-replica deployments.

## Consequences

Retry cost is bounded, every non-clean outcome is visible as `incomplete` or `failed`,
and a prompt can never enable writes that the caller disabled.
