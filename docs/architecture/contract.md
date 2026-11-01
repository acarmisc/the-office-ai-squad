# HTTP contract, finding schema and failure semantics

Every agent exposes the same HTTP contract. The models are in `_common/contract.py`. Requests
are checked with `extra="forbid"`, so an unknown key returns `422`. The JSON Schemas in
`schemas/` are generated from the same models for editors and external checks.

## Endpoints

| Method and path | Purpose | Responses |
| --- | --- | --- |
| `GET /ping` | Liveness. | `200 {"status": "ok"}` |
| `GET /ready` | Readiness: the agent specification loaded. It does not call the model gateway, so a gateway outage does not make a pod unready. | `200 {"status": "ready", "agent": ...}`, or `503` with the load error type |
| `GET /metrics` | Prometheus text format. | `200` |
| `POST /invocations` | Run the agent. | `200` with the result; `202` with `job_id` when `Prefer: respond-async`; `400` for a body that is not JSON; `401` when `SQUAD_API_TOKEN` is set and the bearer token is missing or wrong; `422` with `detail` for validation errors; `503` when the agent did not load |
| `GET /jobs/{job_id}` | State of an asynchronous job: `running`, `done` (with `result`) or `failed`. | `200`; `401` when the token is required and missing or wrong; `404` for an unknown id |
| `POST /webhooks/gitlab`, `POST /webhooks/github` | Webhook receivers, `michael` only, enabled with `WEBHOOK_PROVIDERS`. | See [Review sequence](review-sequence.md). |

`/invocations` and `/jobs/{id}` accept an optional shared bearer token (`Authorization: Bearer <token>`, from `SQUAD_API_TOKEN` or
`SQUAD_API_TOKEN_FILE`). `/ping`, `/ready`, `/metrics` and the webhook routes are not gated by it. With the token unset, the
endpoints are open and each pod logs one warning. Restrict the endpoints by network as well, as described in
[Network and egress](../deployment/network-and-egress.md) and [Hardening](../security/hardening.md#api-authentication).

## Request

Every field is optional except `prompt`.

| Field | Type and limits | Meaning |
| --- | --- | --- |
| `prompt` | string, 1 to 20000 characters | The instruction. For reviews, a sentence is enough. |
| `project` | string, up to 256 | Project key from the registry, or a repository path (`group/repo`). |
| `target` | string, up to 256 | Change request number, issue number or other reference. A numeric target selects a review. |
| `mode` | `review`, `troubleshoot`, `advisor`, `implementer` or `question` | Run mode. A mode the agent does not support is rejected with `422`. |
| `post` | boolean, `true` or `false` | `false` is a dry run. `null` is rejected. When absent, writes are allowed unless the organisation forces dry run. |
| `model` | model alias, up to 128 characters | Overrides the agent's model for this call. |
| `litellm_tags` | up to 20 `key:value` strings | Extra LiteLLM tags for cost attribution. |
| `project_config` | object | Allow-listed per-call overrides: `vcs_provider`, `vcs_base_url`, `vcs_token_secret`, `llm_api_key_secret` (secret names), `skills_repo_path`, `skills_ref`, `config_ref`, and `overrides` (layer 5 of the configuration). |
| `skills` | list of `{name, description, body, source}` | Payload skills, the highest-precedence guidance. `source` is always `payload`. |
| `attachments` | list | Each item has `type` (`image` or `text`), `name`, `media_type`, `data` and `sha256`. The digest must match the data. Only `pam` accepts attachments; other agents return `422`. The data is validated but is not yet passed to the model. |
| `idempotency_key` | string, up to 128 characters | Used as the base of the specialist idempotency keys. |

A minimal review request, validated by the test suite:

<!-- validate: invocation -->
```json
{
  "prompt": "Review change request 42 in project acme/web-app.",
  "project": "acme/web-app",
  "target": "42",
  "mode": "review",
  "post": false,
  "litellm_tags": ["team:storefront"],
  "project_config": {
    "skills_ref": "base",
    "config_ref": "base",
    "overrides": {}
  }
}
```

## Result

`InvocationResult`, returned by every agent and by michael's publication:

| Field | Meaning |
| --- | --- |
| `agent` | Agent id that produced the result. |
| `status` | `complete`, `incomplete` or `failed`. |
| `verdict` | `approve`, `comment`, `request_changes` or `incomplete`. Only the runtime sets `incomplete`; `finish` cannot. |
| `summary` | Text for the change author or the operator. |
| `findings` | List of findings (below). |
| `stats` | `iterations`, `input_tokens`, `output_tokens`, `cost_hint` (currently never set, so `null`), `config_hash`, `skills_applied`, `tool_calls` (attempted calls per tool). |
| `posted` | `notes`, `discussions`, `status` and `urls` written to the VCS. All zero or empty in a dry run. |
| `warnings` | Every degradation, rejected layer, capability fallback and dry-run refusal. Read these. |
| `data` | Agent-specific facts, for example michael's `risk`, `agents` and `contributors`, or pam's `branch` and `checks`. |

Example of a completed review with one finding (abridged; `id` is a stable hash):

```json
{
  "agent": "jim",
  "status": "complete",
  "verdict": "request_changes",
  "summary": "One blocking issue in ProfileCard.tsx.",
  "findings": [
    {
      "id": "3f9a1c0d7e2b4a16",
      "agent": "jim",
      "rule_id": "REACT-SEC-001",
      "category": "security",
      "severity": "blocker",
      "confidence": "high",
      "file": "src/features/profile/ProfileCard.tsx",
      "line_start": 14,
      "line_end": 14,
      "head_sha": "e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1",
      "title": "User bio rendered with dangerouslySetInnerHTML",
      "rationale": "The bio comes from the profile API and is not sanitised.",
      "failure_scenario": "A user saves a bio with a script tag; every viewer runs it.",
      "references": ["CWE-79"]
    }
  ],
  "stats": {"iterations": 6, "input_tokens": 0, "output_tokens": 0, "config_hash": "0123456789abcdef"},
  "posted": {"notes": 0, "discussions": 0, "status": null, "urls": []},
  "warnings": [],
  "data": {}
}
```

The sample is illustrative. Real samples from the eval replays are in [the agent pages](../agents/jim.md).

## Finding

| Field | Type and rule |
| --- | --- |
| `id` | Sixteen hex characters: a hash of agent, file, line range, rule and head sha. Stable for the same finding at the same head. |
| `agent`, `rule_id`, `category` | Strings. `category` is free text in the model; prompts use `correctness`, `security`, `reliability`, `performance`, `a11y`, `maintainability`, `ci-cd`. |
| `severity` | `blocker`, `major`, `minor` or `nit`. |
| `confidence` | `high`, `medium` or `low`. |
| `file`, `line_start`, `line_end`, `head_sha` | Location. `line_end` is not before `line_start`. Lines must lie in a changed hunk to be posted inline; otherwise the finding goes to the summary. |
| `title` | Up to 200 characters. |
| `rationale` | Evidence and consequence. |
| `suggestion` | Optional code, rendered in a fenced block. |
| `references` | CWE, CVE, OWASP, WCAG or documentation links. |
| `failure_scenario` | Required for a `blocker`. |

A `blocker` must have confidence `medium` or `high`, and a `failure_scenario`. The model
validator enforces both when the finding is parsed.

## Failure semantics

| Event | Result |
| --- | --- |
| The agent calls `finish` with a valid verdict. | `status: complete`, the verdict as given. |
| The output is truncated at the token limit, or the agent stops without `finish`. | One retry with a corrective instruction. A second failure is `status: incomplete`, `verdict: incomplete`. |
| `finish` is called with invalid arguments. | The validation error is returned to the model. A second invalid call ends the run as `incomplete`. |
| The turn limit is reached (`limits.max_iterations` or the agent's own limit). | `status: incomplete`, `verdict: incomplete`, warning "iteration limit reached before finish()". |
| The model call raises an error. | `status: failed`, `verdict: incomplete`. Only the exception type is reported. |
| A tool is not classified. | The call is refused and never becomes a metric label. |
| An external-write tool is called under dry run. | The call is refused before it runs and counted in `squad_dry_run_total`. The attempt is counted in `stats.tool_calls`. |
| A specialist times out or fails (michael). | Verdict `incomplete`; the status is `pending`; the summary names the specialist. |
| The organisation configuration is invalid. | Writes are disabled for the run. Webhooks return `503`. |
| The advisory sources are unreachable (dwight). | Findings are marked low confidence; an `approve` is withheld; the run is `comment` (default) or `incomplete` (`security.offline_mode: fail_incomplete`). |

These rules are the reason a reader can trust a verdict: anything that did not finish, or that
ran without its data, is visible as `incomplete` or as a warning.
