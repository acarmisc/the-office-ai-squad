---
title: Troubleshooting method for incidents and failures
source: Google SRE Book (Effective Troubleshooting, Postmortem Culture); Kubernetes debugging documentation (Debug Running Pods, Debug Services); Brendan Gregg, USE method; project process
version: Method guidance; applies to Kubernetes and CI/CD systems in scope
reviewed: 2026-10
---

## Scope

The method `darryl` follows in `troubleshoot` mode: from a symptom to a supported conclusion, using read-only evidence. It applies to incident reports, failing deployments, failing pipelines, and degraded services. It states how to separate facts from inference, how to stop, and how to report what was not checked.

## Rules

### OPS-TSHOOT-001 — Restate the symptom and blast radius

- **Do:** restate the symptom in one sentence with its time window, affected service, namespace or environment, and user-visible impact. Identify what is known to work.
- **Output:** a short statement such as "checkout returns 5xx since 14:00 UTC in namespace shop, about 12 percent of requests; search and login are normal."
- **Why it matters:** wrong scope sends the investigation to the wrong place.
- **Default severity:** not applicable.

### OPS-TSHOOT-002 — Form ranked hypotheses

- **Do:** list two to five hypotheses, ranked by prior likelihood and by how well each explains the blast radius. Include at least one that explains why only part of the traffic fails.
- **Each hypothesis states:** the mechanism, the evidence that would confirm it, and the evidence that would refute it.
- **Why it matters:** without ranking, the search becomes unstructured.

### OPS-TSHOOT-003 — Gather evidence with read-only tools

- **Do:** use read-only tools first: resource status, events, logs (bounded and recent), pipeline and job logs, recent changes, and deployment history. Start with the most recent change before the symptom time.
- **Constraints:** respect bounds (time window, tail length, namespace allowlist). Do not read secrets. Do not run commands that change state.
- **Record:** the query, the time window, and the result count for each piece of evidence.

### OPS-TSHOOT-004 — Confirm or refute each hypothesis

- **Do:** for each hypothesis, mark it confirmed, refuted, or unresolved, citing the evidence.
- **Rule:** a hypothesis is confirmed only by evidence that would not appear if it were false. A timing coincidence alone is not confirmation.
- **Output:** the table of hypotheses with status and evidence.

### OPS-TSHOOT-005 — Separate facts from inference

- **Label:** every statement in the report is one of: observed fact (with source), inference (with reasoning), or unknown.
- **Example:** "Fact: pods in ReplicaSet X logged `connection refused` to port 5432 at 14:02 (kubectl logs, last 200 lines). Inference: the database endpoint changed at 14:00 (ConfigMap updated at 13:59)."
- **Rule:** never state a cause as fact without an observed source.

### OPS-TSHOOT-006 — Conclude with root cause or explicit unknown

- **Do:** conclude with one of two outcomes. (a) A root cause supported by confirmed evidence, stated with the mechanism and the evidence list. (b) "Unknown. The most likely candidates are X and Y. The next checks are A, B, and C."
- **Rule:** do not pick a cause to close the report. An explicit unknown with a next step is a valid result.

### OPS-TSHOOT-007 — Remediation and rollback

- **Do:** propose remediation as steps a human can run, in order, each with its expected effect and its verification. Provide a rollback option for each step that changes state.
- **Rule:** remediation is advice only. `darryl` has no cluster mutation tools. Name the owner or role that should act.
- **Output example:** "1. Revert ConfigMap `db-config` to the previous revision (`kubectl rollout undo` does not apply to ConfigMaps; restore from version control). Verify: readiness probes pass within 2 minutes. Rollback: reapply the new revision."

### OPS-TSHOOT-008 — Report what was not checked

- **Do:** list the checks not performed and why (no access, out of bounds, time limit, tool not configured). Include the systems not covered.
- **Why it matters:** the reader needs to know the confidence limit of the conclusion.

### OPS-TSHOOT-009 — Know when to stop

- **Stop and report** when: the evidence budget is spent, the required access is missing, two independent hypotheses remain with equal support after the cheapest checks, or the next check would require a state change.
- **Report:** the current status, what was ruled out, and the single most useful next action.

### OPS-TSHOOT-010 — Redaction

- **Rule:** redact tokens, passwords, keys, connection strings, and personal data from all quoted output. Quote the minimum needed. Never quote secret resource contents.
- **Default severity:** high if a finding exposes a secret in output.

## How to apply in review

1. Start with the scope (OPS-TSHOOT-001) before any tool call.
2. Write the hypotheses before reading logs, then look for evidence that tests them.
3. Keep a running list of facts with sources, and inferences with reasoning.
4. End with the conclusion type (root cause or unknown), the remediation, the rollback, and the checks not performed.
5. Use `k8s-failure-patterns.md` for Kubernetes symptom families. Use `release-safety.md` when the trigger is a release.
