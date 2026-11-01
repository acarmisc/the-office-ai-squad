# michael: orchestrator

`michael` is the entry point for change requests. It receives webhook deliveries and direct requests,
decides what kind of work is asked for, routes a review to the right specialists, runs them in
parallel, merges their findings and publishes one consolidated outcome. Every specialist can also be
called on its own; `michael` is the only component that publishes a review for a change request.

| Item | Value |
| --- | --- |
| Role | orchestrator |
| Modes | `review`, `troubleshoot`, `implementer`, `question` |
| Default model | `haiku-5-5` (the optional intent classifier). The optional summary narrative uses `MICHAEL_SUMMARY_MODEL`, default `sonnet-5-5`. Routing is deterministic. |
| Max tokens per call | 8192 |
| Max model turns | 25 |
| Own tools | `read_knowledge`, `finish` |
| Writes externally | Review summary, inline discussions and commit status `ai-review/michael` |

## Triggers

| Source | Path | Result |
| --- | --- | --- |
| GitLab webhook (`/webhooks/gitlab`) | Signed delivery, merge request event or comment | Review, security-only review (`/squad sec`), or implementation (issue assigned to the bot) |
| GitHub webhook (`/webhooks/github`) | Signed delivery, pull request event, review request, comment or issue event | As above |
| `POST /invocations` | Direct call, with `mode` or a numeric `target` | Review, incident, implementation or question |
| `squad review <target> --project <key>` | CLI alias of an invocation | Review |

The webhook routes exist only when `WEBHOOK_PROVIDERS` names the provider. The Helm chart does not set
it; see [Ingress and webhooks](../deployment/ingress-webhooks.md).

## Intents

`michael` classifies each request with rules first. A classifier model is used only when the rules
cannot decide and `MICHAEL_LLM_INTENT` is enabled. Without it, an unclassified request is a question,
which performs no writes.

| Intent | Rule | Path |
| --- | --- | --- |
| `mr_review` | Mode `review`, or a numeric target | Routes, fans out, publishes one review |
| `incident` | Mode `troubleshoot`, or words such as incident, alert, 5xx, down or crashloop | `darryl` in troubleshoot mode, read-only. Summary posted as an issue comment only when posting is allowed and the target is a number |
| `implement` | Mode `implementer`, or an implement request with an issue reference | `pam` in implementer mode. `michael` writes nothing itself |
| `question` | Anything else | Answered from the knowledge topics with `finish` |

## Routing

Changed files and manifests choose the specialists. Built-in routes (configurable with
`routing.routes`, where lower layers may only add):

| Changed file | Agent | Condition |
| --- | --- | --- |
| `**/*.tsx`, `**/*.jsx`, `**/*.ts`, `**/*.js` | `jim` | React or Next.js dependency present (`requires: [react]`) |
| `**/*.java`, `**/*.kt`, `**/pom.xml`, `**/build.gradle*` | `angela` | none |
| `.gitlab-ci.yml`, `.github/workflows/**`, `**/Dockerfile*`, `**/*.tf`, `**/Chart.yaml`, `**/values*.yaml`, `deploy/**` | `darryl` | none |
| Every review | `dwight` | `routing.always_run` |
| Configured `extra_agents` routes | the extra agent | its `routes` globs match |

Disabled agents (`agents.<id>.enabled: false`) are removed from the plan. A route with `requires`
applies only when the stack is present in the change or in the manifests.

## Risk tier

Computed from the diff, without a model:

| Tier | Conditions |
| --- | --- |
| `high` | Changed lines at or above `routing.size_thresholds.high` (1000), or a secret-like value added (for example a GitHub or GitLab token pattern, a private key, a hard-coded password or API key). The value itself is never stored; only the pattern name is reported. |
| `medium` | Changed lines at or above `routing.size_thresholds.medium` (300), a sensitive path (`routing.sensitive_paths`), or a dependency manifest changed |
| `low` | Otherwise |

A high tier sends `dwight` a full-scope hint and makes any major finding request changes.

## Fan-out and failure handling

- Specialists run in parallel, up to `routing.fan_out_concurrency` (default 4), each with its own timeout
  from `routing.timeouts_seconds` (`default` is 600 seconds).
- Each call carries an idempotency key `<request key or head sha>:<agent>` and W3C `traceparent` headers.
- One retry is made for transport errors and 5xx responses with the same key.
- Three consecutive failures open a per-agent circuit for 60 seconds, then one probe is allowed.
- Specialist URLs come from `routing.specialist_urls` (organisation only), then
  `ORCHESTRATOR_SPECIALIST_URLS` (`agent=url` pairs), then `http://code-squad-<agent>.<namespace>.svc:8080`
  where the namespace is `POD_NAMESPACE`.

Any failed, timed-out or incomplete specialist makes the verdict `incomplete`. The summary names each one.

## Verdict

| Condition, in order | Verdict |
| --- | --- |
| Any selected specialist failed or did not finish | `incomplete` (status `pending`) |
| Any blocker | `request_changes` |
| High tier and at least one major | `request_changes` |
| Majors at or above `review.verdict.major_threshold` (default 1) | `comment` |
| Otherwise | `approve` |

The verdict is never more lenient than the verdict of a complete specialist. A specialist that withheld an
approval through its own rule (dwight in offline mode) keeps that result. The verdict is computed before
the publication limits (`review.max_findings`, `review.min_confidence_to_publish`), so a hidden finding can
still stop an approval.

## Publication

- One summary note, upserted with the marker `<!-- code-squad:summary:michael -->`.
- Inline discussions for findings that lie in changed hunks at the current head. Each carries its finding
  marker, so a retried job does not duplicate a comment.
- A commit status `ai-review/michael`, from `vcs.status_context_template`. `success` for approve and comment,
  `failed` for request changes, `pending` for incomplete.
- A formal approval is submitted only when `vcs.approve_mode` allows it (default `none`). The squad never
  merges.
- In dry run, nothing is written. The attempted writes appear in `warnings`.

## Tools and policy class

michael's own tools are `read_knowledge` (read) and `finish` (read). The platform performs the review
tools, the specialist calls and the publication outside the model's loop, under the same posting gate.

## Outputs

A real consolidated result, produced by the committed orchestrator with the test fixtures: one changed React file,
`jim` returning one blocker, and `dwight` returning no findings. The specialists are scripted, the routing, risk,
aggregation, verdict and summary are the committed code. `posted` is zero because the run was a dry run.

```json
{
  "agent": "michael",
  "status": "complete",
  "verdict": "request_changes",
  "summary": "### Review by `michael`\n\nVerdict: **request_changes** at head `cccccccccccc`.\n\nReviewed: 1 changed file(s) at head `cccccccccccc`. Intent: `mr_review`. Stacks: react.\nRisk: **low** (no risk signals).\n\n#### Specialists\n\n| Agent | Status | Detail |\n| --- | --- | --- |\n| `jim` | complete | reported |\n| `dwight` | complete | reported |\n\n#### Findings\n\n| Severity | Finding | Location | Reported by |\n| --- | --- | --- | --- |\n| blocker | Unsanitised HTML from the profile bio | src/features/profile/ProfileCard.tsx:17 | jim |\n\n<!-- code-squad:summary:michael -->",
  "findings": [
    {
      "id": "88614bbd1e785688",
      "agent": "jim",
      "rule_id": "REACT-SEC-001",
      "category": "security",
      "severity": "blocker",
      "confidence": "high",
      "file": "src/features/profile/ProfileCard.tsx",
      "line_start": 17,
      "line_end": 17,
      "head_sha": "cccccccccccccccccccccccccccccccccccccccc",
      "title": "Unsanitised HTML from the profile bio",
      "rationale": "The value can be stale when requests overlap.",
      "references": [],
      "failure_scenario": "A bio with a script runs in every viewer's session."
    }
  ],
  "stats": {"iterations": 0, "config_hash": "342b827f709a866c", "skills_applied": []},
  "posted": {"notes": 0, "discussions": 0, "status": null, "urls": []},
  "warnings": ["dry-run blocked 1 external write attempt(s)"],
  "data": {
    "intent": "mr_review",
    "risk": {"tier": "low", "reasons": []},
    "agents": {"jim": "complete", "dwight": "complete"},
    "contributors": {"88614bbd1e785688": ["jim"]},
    "stacks": ["react"]
  }
}
```

The summary's marker is `<!-- code-squad:summary:michael -->`, and the commit status context is `ai-review/michael`.

## Knowledge

`michael` reads the shared React pack and its own README (no topics). Its prompt says that knowledge
topics are trusted, bundled guidelines.

## Configuration that affects michael

| Key | Default | Effect |
| --- | --- | --- |
| `vcs.bot_username` | unset | Required. Without it every webhook event is ignored. |
| `trigger.on_push` | `false` | Also review new pushes to an open change request. |
| `trigger.allowed_commenters` | `[]` (nobody) | Users whose comments may start a run. Lower layers may only narrow it. |
| `trigger.skip_draft` | `true` | Skip draft change requests. |
| `trigger.skip_labels` | `[skip-squad]` | Skip change requests with these labels. |
| `trigger.debounce_seconds` | `30` | Collapses bursts for one head into one run. |
| `routing.routes`, `sensitive_paths`, `always_run` | built-in | Routing and risk inputs. |
| `routing.size_thresholds.*` | `300` and `1000` | Risk tier thresholds. Lower layers may only lower them. |
| `routing.specialist_urls` | `{}` (organisation only) | Specialist base URLs. |
| `routing.timeouts_seconds`, `fan_out_concurrency` | `600`, `4` | Timeouts and parallelism. |
| `routing.specialists_post` | `false` | When true at the organisation level, specialists publish directly. |
| `review.*` | see reference | Publication thresholds and the verdict rule. |
| `vcs.status_context_template` | `ai-review/{agent}` | Commit status name. |
| `vcs.approve_mode` | `none` | Whether approval is ever submitted. |
| `MICHAEL_LLM_INTENT` | off | Enables the classifier model for unclassified requests. |
| `MICHAEL_LLM_SUMMARY`, `MICHAEL_SUMMARY_MODEL` | off, `sonnet-5-5` | Enables a neutral narrative above the summary. The narrative cannot change the verdict or findings. |

## Limits

- Specialist results are only as good as the specialists. `michael` does not re-rate severities.
- Draft changes, skip labels, unauthorised commenters, the bot's own events, and other bots' events are skipped, as configured.
- The `/squad help` command is ignored in this version and returns `202` with a reason.
- Job state and webhook de-duplication are in memory per replica. See
  [Scaling and upgrades](../deployment/scaling-upgrades.md).
- The publication step has no journal. A retried job repeats the same steps, which are idempotent by marker.

## Known weaknesses

- Routing by file name cannot see a risk that is outside the routed files. `dwight` always runs for this reason.
- The risk tier counts changed lines, not their meaning. A small change to an authentication check is
  `medium` only when the path matches `sensitive_paths`.

## How to evaluate

Routing, risk and verdict rules have a deterministic unit-test table in `tests/michael/`. Run
`just test tests/michael`. End-to-end behaviour is covered by the scripted smoke test
(`scripts/smoke_test.sh compose`), which checks that michael answers with `complete` and posts nothing.
