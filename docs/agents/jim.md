# jim: React reviewer

`jim` reviews React and TypeScript changes for correctness, security, reliability,
accessibility and maintainability. It reports findings through a tool and ends with a verdict.
It never edits code, never merges and never approves on its own.

| Item | Value |
| --- | --- |
| Role | react-reviewer |
| Modes | `review` |
| Default model | `sonnet-5-5` |
| Max tokens per call | 8192 |
| Max model turns | 25 |
| Writes externally | `publish_review` only, and only when posting is enabled |

## Triggers

- Routed by `michael` when a changed file matches a React route. The built-in routes are
  `**/*.tsx`, `**/*.jsx`, `**/*.ts` and `**/*.js`, and the route requires a React or Next.js
  dependency in the manifests (`requires: [react]`).
- Called directly with `POST /invocations` and `mode: "review"`, a numeric `target` and
  `project`. This is useful for a second opinion on one change.

## Inputs

The reviewer reads the change through `get_review_context` (metadata, `head_sha`, changed files,
diffs, existing comments, latest CI status and framework hints from the target branch). It then
reads files with `read_file` and searches with `search_repo` and `list_tree`. Project skills come
from `get_project_skills` and `load_skill`. Untrusted content is wrapped in `<untrusted>` blocks.

## Tools and policy class

| Tool | Class | Purpose |
| --- | --- | --- |
| `get_review_context` | read | One call for the change. |
| `read_file` | read | Ranges of files at the head sha or the target branch. |
| `search_repo` | read | Find definitions and callers. |
| `list_tree` | read | Directory listing. |
| `get_project_skills` | read | Names and descriptions of applicable skills. |
| `load_skill` | read | Full text of one skill. |
| `read_knowledge` | read | Topics from the React pack. |
| `publish_review` | external write | Posts inline discussions and the summary. Refused in dry run. |
| `finish` | read | Ends the run with a verdict. |

## Method

1. Read the change context once. 2. Read the framework hints (React version range, strict
TypeScript). 3. Load the skills that match the changed files. 4. Read the knowledge topics the diff
touches, usually three. 5. Read each candidate defect in the head version, then report it.
6. Publish once (when posting is enabled) and finish.

Severity rubric in the prompt: `blocker` needs a concrete failure scenario and at least medium
confidence (for example user HTML rendered with `dangerouslySetInnerHTML`). `major` covers effects
with wrong dependencies, keyboard-inaccessible controls and swallowed async errors. `minor` covers
maintainability and performance with a cost. `nit` is used sparingly.

## Outputs

A real result from the eval replay of the case `react-profile-card` (a profile card with a seeded
set of defects). The replay is scripted, so token counts are fixed. Only the first of four findings
is shown.

```json
{
  "agent": "jim",
  "status": "complete",
  "verdict": "request_changes",
  "summary": "Four issues: unsafe HTML, a fetch race, a hook after an early return and a client key.",
  "findings": [
    {
      "id": "a486593cbd9512db",
      "agent": "jim",
      "rule_id": "REACT-SEC-001",
      "category": "security",
      "severity": "blocker",
      "confidence": "high",
      "file": "src/features/profile/ProfileCard.tsx",
      "line_start": 26,
      "line_end": 26,
      "head_sha": "e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1",
      "title": "Profile bio rendered as raw HTML",
      "rationale": "The bio is passed to dangerouslySetInnerHTML without sanitising. The bio is user-supplied text.",
      "suggestion": null,
      "references": ["CWE-79"],
      "failure_scenario": "A bio containing a script tag runs in the session of every user who views the profile."
    }
  ],
  "findings_total": 4,
  "stats": {
    "iterations": 5,
    "input_tokens": 50,
    "output_tokens": 25,
    "tool_calls": {"get_review_context": 1, "read_file": 1, "load_skill": 1, "publish_review": 1, "finish": 1},
    "skills_applied": ["react-conventions"]
  },
  "posted": {"notes": 0, "discussions": 0, "status": null, "urls": []},
  "warnings": ["dry-run blocked 1 external write attempt(s)"]
}
```

The `publish_review` call was refused by the posting gate, so `posted` is zero and the run still
returns the findings it would have published.

## Knowledge

- The React pack is shared. Topics: `react/hooks-and-effects`, `react/state-and-data-fetching`,
  `react/rendering-performance`, `react/server-components-nextjs`, `react/typescript`,
  `react/accessibility`, `react/forms-and-validation`, `react/error-handling-suspense`,
  `react/testing`, `react/security-adjacent`, `react/dependency-hygiene`,
  `react/component-design`, `react/project-structure`, `react/migrations`. The index is
  `react/index`.
- `jim` has its own pack directory with a README only. To extend `jim`'s knowledge, add topics
  under `src/code_squad/jim/knowledge/`, or use `knowledge_extra_dirs` (organisation level). See
  [Knowledge packs](../onboarding/knowledge-packs.md).
- Because the React pack is shared, `pam` and `michael` can read it too.

## Configuration that affects jim

| Key | Default | Effect |
| --- | --- | --- |
| `agents.jim.enabled` | `true` | Disabling it makes `jim` return `incomplete` without a model call. |
| `agents.jim.model` | `sonnet-5-5` (built-in) | Model alias. |
| `agents.jim.fallback_model` | `null` | Used once after a truncated answer. Not used for overload. |
| `agents.jim.temperature` | built-in `0.0` | Sampling temperature. |
| `agents.jim.max_tokens` | built-in `8192` | Capped by `limits.max_tokens`. |
| `agents.jim.max_iterations` | built-in `25` | Capped by `limits.max_iterations`. |
| `agents.jim.tool_allowlist` | `null` | Subset of jim's tools. `finish` always stays. |
| `agents.jim.prompt_extra` | `null` | Appended as untrusted guidance, capped at `limits.max_prompt_extra_chars` (4000 by default). |
| `agents.jim.budgets.*` | see reference | Not enforced in this version. |
| `agents.jim.severity_overrides`, `disabled_rules`, `language` | empty, `en` | Not applied in this version. |
| `review.min_confidence_to_publish` | `medium` | Findings below are not published. |
| `review.min_severity_inline` | `minor` | Lower findings go to the summary. |
| `review.max_findings` | `30` | Maximum findings published per run. |
| `review.ignore_globs` | generated, lock and snapshot paths | Files are excluded; findings on them are demoted to general notes. |
| `skills.*` | paths `.agents/skills`, `.claude/skills`, `.squad/skills`; ref `base` | Where project skills come from and their limits. |
| `vcs.approve_mode` | `none` | When `jim` runs standalone with posting enabled, `publish_review` may submit a formal approval if this allows it. Under `michael` the specialist does not post, and michael decides. |
| `posting.force_dry_run` | `false` | Organisation switch: no writes at all. |

Full reference: [Configuration](../reference/configuration.md).

## Limits

- About ten tool calls are the target. The prompt asks for range reads, not whole files.
- It does not know the React version unless the manifests say so. When the version is unknown it
  avoids version-specific APIs and says so in the summary.
- A truncated diff is noted in the summary and only the visible hunks are reviewed.

## Known weaknesses

- Findings depend on the model's reading of the code. Seeded-defect recall is measured only in
  replay mode, which checks the pipeline and not model quality.
- Server Components and Next.js advice applies only when that code is present; mixed projects can
  produce noise.
- Accessibility findings rely on the markup visible in the diff. Computed styles and runtime focus
  order are not checked.

## How to evaluate

1. Run the replay: `just eval` (or `uv run python -m eval.run`). The report lists recall,
   precision, false-blocker rate and must-not-flag hits for the `react-*` cases.
2. Add a golden case under `eval/cases/` for a new defect class, with a replay file under
   `eval/replays/`. See [Testing](../testing/index.md).
3. For a live check, set `EVAL_LIVE=1` and `LLM_BASE_URL`, then run `uv run python -m eval.run --live`.
   Live results are not produced by the default gate.
