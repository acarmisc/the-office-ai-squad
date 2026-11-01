# 0010 — Single publication path through the orchestrator

- Status: accepted
- Date: 2026-11-01

## Context

A change request can be reviewed by several specialists (jim, angela, dwight, darryl and
configured extra agents). Each specialist could publish its own inline comments, summary
and commit status. Then a reviewer sees several summaries, several statuses and no single
answer, and a failed or slow specialist is invisible in the outcome. The brief (§10)
asks for one publication, one summary and an explicit `incomplete` when any specialist
did not finish.

The findings pipeline (`_common/findings.py`) derives the verdict and the commit status
from the findings alone. It cannot publish an `incomplete` outcome, so it cannot be the
publication step of the orchestrator as it stands.

## Decision

- Specialists are called with `post: false`. The orchestrator sends `post: true` only
  when `routing.specialists_post` is set, and that setting can only be kept false by
  lower layers. The orchestrator is the only component that publishes a review for
  `mr_review`. Its status context is `ai-review/michael`, and its summary carries the
  marker `<!-- code-squad:summary:michael -->`.
- The orchestrator never reports `success` for an incomplete run. Any specialist that
  times out, fails or returns an incomplete result makes the consolidated verdict
  `incomplete`, which is published as `pending`. The summary names every such specialist
  and the reason.
- Publication lives in `michael/publish.py`. It reuses the findings building blocks
  (anchoring, policy, marker dedupe, inline body rendering) and takes the verdict from the
  consolidated report. `findings.publish` gained a verdict cap (approve, comment or
  request_changes) but still has no `incomplete` state, so it cannot publish a
  consolidated incomplete outcome. It keeps serving the specialists that publish directly.
- The consolidated verdict is never more lenient than the verdict of any complete
  specialist. A verdict a specialist withheld through its own cap (dwight in offline
  mode) therefore survives the merge.
- The verdict is computed from all aggregated findings, before the publication policy
  (`min_confidence`, `max_findings`) drops any of them. A hidden low-confidence major can
  therefore still turn `approve` into `comment`. This is deliberate: nothing the policy
  hides can make the verdict more lenient.
- Specialist calls use a per-agent timeout enforced by the fan-out, a single retry with
  the same idempotency key for transport errors and 5xx responses, and a circuit breaker
  per agent (three consecutive failures open it for 60 seconds, with one probe after the
  cool-down). Idempotency keys are `<request key or head sha>:<agent>`.
- Trace context is forwarded to specialists as W3C `traceparent` headers.
- The LLM intent classifier is opt-in (`MICHAEL_LLM_INTENT`). Without it, a request that
  the rules cannot classify is a `question`, which performs no writes. The summary
  narrative is opt-in too (`MICHAEL_LLM_SUMMARY`, model `MICHAEL_SUMMARY_MODEL`, default
  `sonnet-5-5`).
- Webhook deliveries are verified (GitLab token or GitHub HMAC over the raw body), then
  de-duplicated by delivery id, then answered with 202 immediately. The review runs as an
  asynchronous job. A debounce window collapses repeated events for the same project,
  change request and head.
- Extra agents are registered at startup from the organisation configuration. Their tool
  set comes from a preset that can contain only `publish_review` as an external write,
  and the posting gate still applies.

## Consequences

- One summary and one commit status per change request, whatever the number of
  specialists. Partial failure is visible in the status and in the summary.
- Specialists keep their own publication code for standalone use. With
  `specialists_post: true` a specialist may publish directly, and the orchestrator then
  has no control over that publication. It is off by default and org-only.
- The job store is in process. Jobs and the webhook delivery de-duplication are visible
  only to the replica that received them, so webhook-driven reviews need one replica or a
  shared session store. Redis (`SESSION_STORE_URL`) moves job state, but the webhook
  de-duplication and the debounce window still live in memory. Both are documented as a
  limitation for high availability.
- The publication step has no journal. A retried job re-runs the same idempotent steps:
  marker-based inline comments are skipped when already present and the summary is
  upserted. A status update is repeated with the same value.
- Incident results are posted as issue comments only when the target is a number, which
  must then be an issue number. Implementation results are not written by the
  orchestrator, because pam opens its own change request.
- Trigger settings `trigger.events`, `trigger.skip_wip_titles` and
  `trigger.skip_bot_authors` are not read by the webhook gateway yet. Draft change
  requests, skip labels, `allowed_commenters` and `on_push` are enforced. The WIP title
  and bot author checks are always on in `decide_trigger`.
- A delivery id is recorded when first seen, even if the event is later refused (for
  example because the organisation configuration is invalid). A redelivery of the same
  id is then reported as a duplicate.
- Open for review: whether a formal approval should ever be submitted by the orchestrator
  (`vcs.approve_mode`, default `none`); the squad never merges.
