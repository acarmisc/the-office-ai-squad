# angela: Java reviewer

`angela` reviews Java and JVM changes, including Spring applications, for correctness, concurrency,
resource handling, persistence, API compatibility and security. It works like `jim`: it reads the
change, reports findings through a tool and finishes with a verdict.

| Item | Value |
| --- | --- |
| Role | java-reviewer |
| Modes | `review` |
| Default model | `sonnet-5-5` |
| Max tokens per call | 8192 |
| Max model turns | 25 |
| Writes externally | `publish_review` only, and only when posting is enabled |

## Triggers

- Routed by `michael` when a changed file matches a Java route: `**/*.java`, `**/*.kt`,
  `**/pom.xml`, `**/build.gradle*`.
- Called directly with `POST /invocations` (`mode: "review"`, a numeric `target`, and `project`).

## Inputs

The same context tools as `jim`: `get_review_context`, `read_file`, `search_repo`, `list_tree`,
skills, and the knowledge topics. The Java build file tells the reviewer the target release.
Advice that needs a newer language level than the project compiles is not given.

## Tools and policy class

| Tool | Class | Purpose |
| --- | --- | --- |
| `get_review_context` | read | One call for the change. |
| `read_file` | read | Ranges of files at the head sha or the target branch. |
| `search_repo` | read | Find definitions, callers and configuration. |
| `list_tree` | read | Directory listing. |
| `get_project_skills` | read | Applicable project skills. |
| `load_skill` | read | Full text of one skill. |
| `read_knowledge` | read | Topics from the Java pack. |
| `publish_review` | external write | Posts findings. Refused in dry run. |
| `finish` | read | Ends the run with a verdict. |

## Method

1. Read the change context and the build file (target release, Spring presence).
2. Load the skills and the knowledge topics that match the diff. `java/build-hygiene` comes first
   when release-dependent advice is needed.
3. For each candidate, read the code in the head version and confirm the path.
4. Publish once when posting is enabled, then finish.

Rubric highlights: `blocker` for SQL or JPQL built by concatenation, a secret written to a log, or
untrusted input deserialised with default typing. `major` for swallowed exceptions, check-then-act on
shared state, N+1 queries on request paths, and resources that can leak. `minor` and `nit` for
maintainability and small performance costs.

## Outputs

A real result from the eval replay of the case `spring-order-service`. Only the first of three
findings is shown.

```json
{
  "agent": "angela",
  "status": "complete",
  "verdict": "request_changes",
  "summary": "Three issues: JPQL concatenation, a bypassed transaction and a swallowed exception.",
  "findings": [
    {
      "id": "07da3cf574fa449d",
      "agent": "angela",
      "rule_id": "JAVA-JPA-001",
      "category": "security",
      "severity": "blocker",
      "confidence": "high",
      "file": "src/main/java/com/example/orders/OrderService.java",
      "line_start": 20,
      "line_end": 20,
      "head_sha": "f2f2f2f2f2f2f2f2f2f2f2f2f2f2f2f2f2f2f2f2",
      "title": "JPQL built by concatenating the status parameter",
      "rationale": "The status value is concatenated into the query text instead of bound as a parameter.",
      "suggestion": null,
      "references": ["CWE-89"],
      "failure_scenario": "A status value containing a quote changes the query and returns or changes rows outside the request."
    }
  ],
  "findings_total": 3,
  "stats": {
    "iterations": 5,
    "input_tokens": 50,
    "output_tokens": 25,
    "tool_calls": {"get_review_context": 1, "read_file": 1, "read_knowledge": 1, "publish_review": 1, "finish": 1},
    "skills_applied": []
  },
  "posted": {"notes": 0, "discussions": 0, "status": null, "urls": []},
  "warnings": ["dry-run blocked 1 external write attempt(s)"]
}
```

## Knowledge

The Java pack lives in `src/code_squad/angela/knowledge/java/`. Topics: `java/index` (rule prefixes),
`java/build-hygiene`, `java/null-safety-optional`, `java/immutability-equality`,
`java/resources-exceptions`, `java/concurrency`, `java/collections-streams`, `java/spring-core`,
`java/jpa-persistence`, `java/api-compat-logging`, `java/testing`, `java/performance`.

The shared React pack is also readable by `angela`, but it is not relevant to Java code and adds
noise to its search results. A deployment with Java-only projects can keep it out of the way by
relying on the prompt's scope.

## Configuration that affects angela

| Key | Default | Effect |
| --- | --- | --- |
| `agents.angela.enabled` | `true` | When false, `angela` returns `incomplete` without a model call. |
| `agents.angela.model` | `sonnet-5-5` (built-in) | Model alias. |
| `agents.angela.fallback_model` | `null` | Used once after a truncated answer. |
| `agents.angela.max_tokens`, `max_iterations`, `temperature` | built-in | Capped by `limits.*`. |
| `agents.angela.knowledge_extra_dirs` | `[]` (org-only) | Extra absolute directories searched for topics after the built-in packs. |
| `agents.angela.prompt_extra` | `null` | Untrusted guidance, length-capped. |
| `review.*` | see [Configuration](../reference/configuration.md) | Same thresholds as `jim`. |
| `routing.routes` | Java routes built in | Add routes for other JVM languages. |
| `skills.*` | `.agents/skills`, `.claude/skills`, `.squad/skills` | Skill discovery and limits. The Java-specific discovery defaults are the same paths. |

## Limits

- The reviewer cannot run the build or tests. It reasons from the code and the build file.
- Concurrency findings are judged from the code visible in the diff and its callers. Thread-safety
  claims that depend on a framework's threading model are reported with lower confidence.
- Spring behaviour depends on the framework version. The build file gives a hint; the prompt tells
  the model not to guess.

## Known weaknesses

- Long files are reviewed in ranges. A defect whose cause is far from the diff can be missed.
- Mockito and Testcontainers advice can be generic when the project has its own test helpers.
  Project skills should say which helpers to prefer.

## How to evaluate

Run `just eval`, which covers the two `spring-*` cases. Recall, precision, false-blocker rate and
must-not-flag hits are reported per case. To add a defect class, add a fixture change under
`eval/fixtures/spring-app/`, a golden case under `eval/cases/` and a replay under `eval/replays/`.
See [Testing](../testing/index.md).
