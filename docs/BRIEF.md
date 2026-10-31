# BUILD PROMPT — "Code Squad": specialised review & engineering agents (Kubernetes-portable)

> Original build brief, kept verbatim in the repository so any contributor or agent can resume work cold.
> Audience: an autonomous coding agent running a long session, with no human available for questions.
> Goal: deliver the finished, tested, documented, deployable project described below.
> Language: this brief is in English. All code, prompts, docs and agent outputs are in English.

---

## 0. How to work (read first, follow throughout)

You are a senior engineer/architect building this project end to end. You will not be able to ask questions. When something is ambiguous, pick the option in §2 or the most conservative reasonable one, record it in `docs/decisions/NNNN-title.md` (short ADR: context, decision, consequences) and move on. Only stop if something is genuinely impossible, and then write the blocker in `STATUS.md` and continue with every part that is not blocked.

**Terminology:** "MR" in this brief means a GitLab merge request **or** a GitHub pull request. In code the abstraction is `ChangeRequest`; "CI" means GitLab CI/CD **or** GitHub Actions.

**Operating protocol**

1. Start by creating `STATUS.md` (milestone checklist from §14, current milestone, open risks, decisions pointer). Update it at every milestone so the session can be resumed cold from the repo alone.
2. Create a task list from §14 and keep it current.
3. Work milestone by milestone. A milestone is done only when its acceptance criteria pass and `just check` is green. Commit at the end of each milestone (conventional commits, imperative, scoped), never leave the tree broken.
4. Test first for bugs and for every security-relevant behaviour (tool policy, dry-run, prompt-injection handling, input validation).
5. Never invent library APIs from memory. Before using Strands Agents, FastAPI, the Kubernetes Python client, OpenTelemetry, or any external API (GitLab, OSV, NVD, GHSA, CISA KEV, EPSS), check the installed package's real signatures (`python -c "import x; help(x.Y)"`, source in site-packages) or the official docs, and pin versions in `uv.lock`. If web access is available, verify current best-practice claims you embed in knowledge files and date them.
6. Never put secrets in code, tests, fixtures, logs or docs. Use obvious fakes in tests.
7. Do not spend effort on cosmetics or speculative features beyond this brief. Do not refactor unrequested things. No code comments unless they explain a non-obvious *why*.
8. At the end, run the full validation in §15, fix everything, and finish with a short `docs/HANDOFF.md` (what exists, how to run, known limits, next steps).

**Code conventions** (inherited from the reference squad)

- Python ≥ 3.12, `uv` + `uv.lock`, build backend `hatchling`, `src/` layout.
- `ruff` (E, W, F, I, UP, B, SIM, RUF; line length 88), `mypy --strict` on `src`, `tests`, `deploy`, `scripts`, `eval`, `pytest`.
- Short functions; `Enum` / `Literal` instead of boolean parameters; private by default (`_name`); frozen dataclasses or pydantic models for data; explicit types everywhere.
- Agent names: lowercase single token. Commit messages and docs in English.

---

## 1. Context and what to reuse from the reference squad

An existing squad ("CES AI Agents", nine agents on AWS Strands Agents SDK, deployed on AWS Bedrock AgentCore, Python 3.12) is the reference. You do not have its repo, so its relevant design is summarised here. Reuse the **ideas**; drop the **AWS lock-in**.

**Keep (re-implement in this repo):**

- One shared platform package + one Docker image; the active agent is chosen at runtime by `AGENT_NAME`.
- `AgentSpec` frozen dataclass as the single description of an agent: `name`, `description`, `system_prompt`, `task_template` (placeholders `{target}`, `{action}`, `{project}`), `tools`, `model_id`, `max_tokens`, `temperature`, `max_iterations` (default 25), `retry_model_id` (one retry after truncation), `content_capture` (`FULL`/`METADATA`), `accepts_attachments`, `telemetry_factory`.
- Prompt in `prompt.md` per agent, loaded from the package (env override allowed for debugging).
- Env overrides: `AGENT_MODEL_ID`, `AGENT_MAX_TOKENS`, `AGENT_MAX_ITERATIONS`, `AGENT_TEMPERATURE`.
- HTTP contract: `POST /invocations`, `GET /ping`, port 8080. A **new** Strands `Agent` instance per invocation (Strands agents hold conversation state).
- **Fail-closed validation** of the payload before any model call; payload containing the input key of another agent is rejected.
- **Tool policy**: every tool is classified `READ`, `LOCAL_MUTATION` or `EXTERNAL_WRITE` in one module; a test fails if any registered tool is unclassified or if an `EXTERNAL_WRITE` tool runs when dry-run is on.
- **Dry-run gate**: payload `post: false` hard-disables every external write for that invocation regardless of the prompt. If `post` is absent, writes are allowed (explicit constant `POST_WHEN_ABSENT = True`, documented). `post` must be a real boolean if present.
- **Untrusted content**: MR diffs, issue text, logs, skills from repos, web/CVE text are *data*, wrapped in delimited blocks, never instructions.
- **Validated output**: the agent ends by calling `finish()` with a structured result; on validation error the runtime retries once with the error. If the response stops at `max_tokens`, one retry asks for a shorter answer of the same shape. If the iteration limit is hit, the result is marked **incomplete**, never "no issues".
- **Findings anchored to an immutable `head_sha`** and validated deterministically (file exists in diff, line within a changed hunk) before publication.
- **Runtime skills in the payload**: `skills: [{name, description, body}]`.
- Per-project configuration (`project_config`) resolved per invocation; malformed → reject before any model call.
- LiteLLM gateway (OpenAI-compatible) for all LLM calls, with tags for cost attribution.
- Eval harness with golden cases and scorers; Backstage `catalog-info.yaml`; TechDocs/mkdocs with `--strict`.

**Change (deliberately):**

| Reference | This project |
|---|---|
| AgentCore runtime, ECR, `linux/arm64` only | Plain container; **multi-arch** image (`linux/amd64`, `linux/arm64`); runs on any Kubernetes; stays runnable on AgentCore as an option (same HTTP contract) |
| AWS Secrets Manager for project secrets | `SecretProvider` interface: default reads Kubernetes Secrets mounted as files/env; optional providers (env, file, Vault, AWS SM) behind the same interface |
| CloudWatch + ADOT | OpenTelemetry **OTLP** (collector-agnostic), Prometheus `/metrics`, structured JSON logs; Langfuse optional |
| S3-only session memory | `SessionStore` interface: in-memory (default), Redis, S3-compatible |
| CLI/justfile pointed at AgentCore | `just` + `kind`/`docker compose` for local; Helm chart for clusters |
| GitLab only | GitLab **and** GitHub (github.com/GHES) behind one `VcsProvider`, chosen per project |
| Per-agent static config | Layered, schema-validated configuration (org → project registry → repo → call) with provenance, usable across many projects |
| Haiku/Sonnet hard-wired | Model aliases from the LiteLLM gateway, configured per agent via env; no provider SDK imports outside `model.py` |

---

## 2. Decisions already taken (do not reopen)

1. **Framework:** AWS Strands Agents SDK (open source, model-agnostic) in Python, served by **FastAPI + uvicorn** with the reference HTTP contract. Not tied to AgentCore.
2. **Runtime skills:** hybrid. Skills may arrive in the payload (`skills[]`) and/or be discovered in the target repository; precedence and trust rules in §6.
3. **Orchestrator:** yes — router **and** aggregator, mostly deterministic code with an LLM only for ambiguous routing and for the consolidated summary. Every specialist remains independently invocable.
4. **Frontend engineer:** implements code in an isolated sandbox and opens a merge request **autonomously, with no human approval step before the MR is created**; also supports an advisor-only mode (§9).
5. **Defaults (every one of them overridable by configuration, never by editing code; see §4.8):** **GitLab and GitHub are both first-class** (GitLab SaaS/self-managed; github.com and GitHub Enterprise Server), selected per project by configuration and usable side by side in one deployment (§4.7); Jira for tickets (optional in this version, interface only for the tools that need it); LLM via LiteLLM at `LLM_BASE_URL` with `LLM_API_KEY`; reasoning agents default to alias `sonnet-5-5`, cheap router/summariser default to `haiku-5-5`; LiteLLM first tag `squad:code-squad`.
6. Repository name `code-squad`, Python package `code_squad`. **Agent ids are characters from The Office (US)**: `michael` = orchestrator, `jim` = React reviewer, `angela` = Java reviewer, `dwight` = security reviewer, `darryl` = DevOps specialist, `pam` = senior frontend engineer. Ids are lowercase single tokens, used for `AGENT_NAME`, package directories (`src/code_squad/<id>/`), Kubernetes object names (`code-squad-<id>`), commit statuses (`ai-review/<id>`) and branches (`<id>/<task-key>-<slug>`). The functional role names are used in docs and in each `prompt.md` title (e.g. "Dwight — security reviewer"), so the ids stay discoverable. Keep the mapping in one place (`registry.py`) and in the docs table. Do not add character humour to prompts or outputs: the persona is only a name, outputs stay professional.

---

## 3. The squad

| id | Functional role | Description | Writes externally? | Default model alias |
|---|---|---|---|---|
| `michael` | orchestrator | Detects stack/intent, fans out to specialists, dedupes and consolidates, posts the single verdict | Yes (summary note, commit status) | `haiku-5-5` (routing), `sonnet-5-5` (summary) |
| `jim` | react-reviewer | Code review of React/TypeScript changes, project-specific skills at runtime | Yes (inline discussions, summary) | `sonnet-5-5` |
| `angela` | java-reviewer | Code review of Java/JVM changes (Spring and plain Java), project-specific skills at runtime | Yes | `sonnet-5-5` |
| `dwight` | sec-reviewer | Security posture of code and dependencies, embedded guidelines, live CVE lookup | Yes | `sonnet-5-5` |
| `darryl` | devops | CI/CD, Docker, IaC, Kubernetes manifest review **and** read-only production troubleshooting | Yes (comments only) | `sonnet-5-5` |
| `pam` | frontend-dev | Senior React engineer: implements tasks, runs checks, opens the MR autonomously; advisor mode | Yes (branch push, MR creation) | `sonnet-5-5` |

Common behaviour for all reviewers: read context in as few calls as possible, produce findings with the schema in §4.3, deduplicate against existing comments, publish idempotently, set commit status `ai-review/<agent-id>` (success / failed / pending with description).

---

## 4. Platform architecture (`src/code_squad/_common/`)

### 4.1 Layout

```
code-squad/
├── pyproject.toml, uv.lock, justfile, AGENTS.md, README.md, STATUS.md, mkdocs.yml, catalog-info.yaml
├── src/code_squad/
│   ├── _common/
│   │   ├── spec.py            AgentSpec
│   │   ├── registry.py        AGENTS, get_spec(), env overrides
│   │   ├── runtime.py         create_agent(), run_task(), iteration/truncation/retry handling
│   │   ├── model.py           OpenAI-compatible model builder for LiteLLM (only place importing provider code)
│   │   ├── contract.py        pydantic: InvocationRequest, InvocationResult, Finding, Verdict
│   │   ├── validation.py      fail-closed payload validation
│   │   ├── tool_policy.py     READ / LOCAL_MUTATION / EXTERNAL_WRITE classification
│   │   ├── posting.py         dry-run gate
│   │   ├── untrusted.py       delimiting/escaping of untrusted blocks
│   │   ├── findings.py        deterministic anchoring/validation, dedup, idempotent markers
│   │   ├── vcs/               base.py (VcsProvider protocol + capability flags), gitlab.py, github.py, factory.py, issues/ (IssueTracker: gitlab, github, jira read-only), conformance/ (shared provider test-suite)
│   │   ├── config/            schema.py (pydantic, single source of truth), loader.py (layering), merge.py (tighten-only rules), projects.py (project registry), explain.py (provenance), cli.py
│   │   ├── secrets/           base.py (SecretProvider), k8s_files.py, env.py (+ optional vault.py)
│   │   ├── skills/            loader.py, discovery.py, validate.py, cache.py (see §6)
│   │   ├── sandbox/           base.py, local_process.py, k8s_job.py (see §9)
│   │   ├── session.py         SessionStore: memory / redis / s3-compatible
│   │   ├── observability.py   OTel OTLP, Prometheus metrics, JSON logging, Langfuse optional
│   │   ├── safe_retry.py      retry with operation journal (no double-posting)
│   │   ├── prompt_loader.py
│   │   └── cli.py             `squad <agent> review <target>` etc.
│   ├── michael/  jim/  angela/  dwight/  darryl/  pam/
│   │   ├── __init__.py        exposes SPEC
│   │   ├── prompt.md
│   │   ├── tools.py           agent-specific tools
│   │   └── knowledge/         embedded guideline files (markdown, dated, versioned)
│   └── server.py              FastAPI app factory (AGENT_NAME selects the agent)
├── deploy/ Dockerfile, sandbox-node.Dockerfile, helm/code-squad/, compose.yaml, kind/
├── eval/ golden cases, fixtures, scorers
├── schemas/ generated JSON Schemas (config, projects, invocation, finding)
├── examples/ org, repo, gitlab, github configuration examples (§17)
├── skills/ example project skills (react, java) used by tests and docs
├── scripts/ ...
├── tests/
└── docs/ (architecture, agents, skills, security, deployment, decisions/)
```

### 4.2 HTTP contract (server.py)

- `GET /ping` → 200 `{"status":"ok"}` (liveness). `GET /ready` → readiness (spec loaded, model gateway reachable-optional). `GET /metrics` → Prometheus.
- `POST /invocations` → synchronous result. Optional header `Prefer: respond-async` → 202 with `job_id`; `GET /jobs/{id}` returns state/result (Redis-backed if configured, in-memory otherwise; document the single-replica caveat). Optional SSE progress stream is a nice-to-have, not required.
- `POST /webhooks/gitlab` and `POST /webhooks/github` (michael only; each enabled by config): GitLab verifies `X-Gitlab-Token`, GitHub verifies `X-Hub-Signature-256` (HMAC-SHA256 over the raw body), both with constant-time compare; deduplicate by delivery id; ignore events authored by the bot's own identity (loop prevention); trigger on "change request assigned to / review requested from the bot", "opened/updated/ready-for-review" when the project config says `trigger.on_push: true`, issue assigned to the bot (for `pam`), and comment mention `@<bot>` / slash command (`/squad review`, `/squad sec`, `/squad implement`, `/squad help`) from authorised users only (`trigger.allowed_commenters`); ignore everything else; respond fast and process asynchronously.
- Request body (all fields validated by pydantic with `extra="forbid"`):

```json
{
  "prompt": "review change request 42",
  "project": "group/repo",
  "target": "42",
  "mode": "review",
  "post": false,
  "model": "sonnet-5-5",
  "litellm_tags": ["k:v"],
  "project_config": {
    "vcs_provider": "gitlab | github",
    "vcs_base_url": "https://gitlab.example.com",
    "vcs_token_secret": "name-of-secret",
    "llm_api_key_secret": "name-of-secret",
    "skills_repo_path": ".agents/skills",
    "skills_ref": "base",
    "config_ref": "base",
    "overrides": { "agents": { "dwight": { "model": "sonnet-5-5" } } }
  },
  "skills": [{"name": "...", "description": "...", "body": "...", "source": "payload"}],
  "attachments": [{"type": "image|text", "name": "...", "media_type": "...", "data": "...", "sha256": "..."}]
}
```

- `project` is either a key in the project registry (§4.8) or a repository path (`group/repo`, `owner/repo`) resolved through it; the provider and credentials are derived from the registry, and `project_config` only carries the allow-listed per-call overrides below. `project_config` keys are an allow-list; `*_secret` values are *names* resolved through `SecretProvider`, never raw secrets. Unknown keys → 422.
- Response: `InvocationResult` = `{agent, status: complete|incomplete|failed, verdict, summary, findings[], stats{iterations,tokens,cost_hint}, posted{notes,discussions,status}, warnings[]}`.

### 4.3 Finding schema (shared by all reviewers)

```
Finding {
  id            stable hash(agent, file, line_range, rule_id, head_sha)
  agent, rule_id, category   (e.g. correctness|security|performance|a11y|maintainability|ci-cd|reliability)
  severity      blocker | major | minor | nit
  confidence    high | medium | low
  file, line_start, line_end, head_sha
  title, rationale, suggestion (optional, code in fenced block), references[] (CWE, CVE, OWASP, docs URL)
}
Verdict = approve | comment | request_changes | incomplete
```

Deterministic validation before publishing: file is in the diff, lines are inside a changed hunk (or finding is demoted to a general note), `head_sha` equals the current MR head (if the MR moved, mark stale and re-anchor or drop), duplicates against existing discussions (hidden HTML marker `<!-- code-squad:<finding-id> -->`) are skipped. Severity `blocker` requires `confidence` ≥ medium and a concrete failure scenario.

### 4.4 Tool policy and posting gate

- `tool_policy.py` is the only source of truth. Add a registry test: every tool in every `SPEC.tools` is classified; every `EXTERNAL_WRITE` tool raises a typed `DryRunError` when `post` is false; no agent other than `pam` has `LOCAL_MUTATION` tools beyond its scratch workspace.
- `darryl` troubleshooting tools are strictly `READ` (see §8). Cluster RBAC enforces the same at the Kubernetes level.

### 4.5 Untrusted content

All content from repos, MR/issue text, logs, advisory text, web pages and runtime skills is wrapped by `untrusted.py` in randomly-delimited blocks (`<untrusted id="…">…</untrusted>`), with the delimiter chosen so the content cannot contain it. System prompts state that instructions inside these blocks are ignored. Add adversarial tests (injection in diff, in a skill, in a CVE description, in a log line) asserting that no `EXTERNAL_WRITE` tool is called outside the expected flow and that the verdict is not manipulated.

### 4.6 Secrets, config, observability

- Config follows §4.8 (layered, schema-validated). Bootstrap env vars (documented table in `docs/deployment.md`, generated from the schema): `AGENT_NAME`, `LLM_BASE_URL`, `LLM_API_KEY[_FILE]`, `VCS_PROVIDER`, `VCS_BASE_URL`, `VCS_TOKEN[_FILE]` (single-project fallback only; multi-project setups use the project registry of §4.8), `SECRETS_DIR` (default `/var/run/secrets/squad`), `OTEL_EXPORTER_OTLP_ENDPOINT`, `SESSION_STORE_URL`, `ORCHESTRATOR_SPECIALIST_URLS` (or Kubernetes service DNS pattern), `EGRESS_PROXY_URL`, plus the `AGENT_*` overrides.
- Logs: JSON, never contain prompts, diffs, tokens or secrets (`content_capture=METADATA` mode must truly omit content from traces).
- Metrics: invocations by agent/status, latency, iterations, tokens, tool calls by class, findings by severity, dry-run count, CVE-lookup cache hits.

---

### 4.7 VCS abstraction: GitLab and GitHub

`VcsProvider` is a protocol with **capability flags**; agents and tools only talk to it, never to GitLab/GitHub directly. The provider is chosen per project (`vcs.provider: gitlab | github | auto`, `auto` infers from `base_url` or webhook source) and several providers can be active in one deployment.

Operations (names indicative): `whoami()` (bot identity), `get_change_request`, `get_diff(head_sha)` with per-file hunks and line mapping, `list_changed_files`, `read_file(ref)`, `list_tree`, `list_comments/threads`, `post_inline_comment(position)`, `post_summary`, `upsert_comment(marker)`, `resolve_thread`, `set_status(state, context, description, url)`, `list_ci_runs/jobs`, `get_job_log`, `create_branch`, `push` (git over HTTPS through a credential helper), `create_change_request(title, body, draft, labels, reviewers, assignees)`, `add_labels`, `request_reviewers`, `get_default_branch`, `is_protected(branch)`, `get_issue/comment_on_issue`, rate-limit introspection.

| Concern | GitLab | GitHub |
|---|---|---|
| API | REST v4 (GraphQL optional), SaaS or self-managed `base_url` | REST (GraphQL where needed), github.com or GHES `base_url` |
| Auth | Personal/project/group access token, optionally OAuth | **GitHub App** preferred (app JWT RS256 → installation token, cached, auto-refreshed, scoped to the repo), PAT fallback |
| Inline comments | Discussions with `position` (needs `base_sha`, `start_sha`, `head_sha` from diff refs) | Pull-request review with batched comments (`commit_id`, `path`, `line`, `side`) |
| Verdict signal | Commit status `ai-review/<id>`; optional approval via approvals API | Check run with annotations (App) else commit status; review event `COMMENT` / `REQUEST_CHANGES` / `APPROVE` |
| CI introspection | Pipelines, jobs, traces, environments, deployments | Actions workflow runs, jobs, logs, deployments |
| Draft | Draft MR | Draft PR |
| Webhook auth | `X-Gitlab-Token` | `X-Hub-Signature-256` HMAC, delivery id |

Rules:
- `vcs.approve_mode: none | comment | approve` (default `none`): whether a positive verdict may trigger a formal approval/`APPROVE` review. Never default to approving. The squad never merges.
- Capability fallback: if a capability is missing (e.g. check runs with a PAT) use the documented fallback (commit status) and record it in `warnings[]`; unsupported operations raise a typed `CapabilityError`, never fail silently.
- Robustness: pagination, timeouts, retry with jitter on 5xx/429, honour GitHub primary and secondary rate limits and GitLab `Retry-After`, truncated or missing GitHub patches (large/binary files) fetched via contents/compare, GitLab `diff_refs` staleness handling, idempotent upserts via the hidden marker (§4.3), no duplicate comments on retried deliveries.
- Forks: review of change requests from forks is allowed through the API diff; **never execute fork code** (reviewers have no sandbox; `pam` works only on branches of the target repo).
- Bot-loop prevention: ignore events authored by the bot identity; ignore comments from non-authorised users.
- Conformance suite (`vcs/conformance/`): one parametrised test-suite run against the in-memory fake, the GitLab provider and the GitHub provider using recorded HTTP fixtures (e.g. `respx`); covers every operation above, pagination, rate-limit, stale head, fork PR, large diff. Adding a provider (e.g. Bitbucket, Gitea) means implementing the protocol and passing this suite; document the steps in the contributing guide.
- `IssueTracker` interface (GitLab issues and GitHub issues implemented; Jira read-only adapter) used by `pam` to read tasks and by `michael` to comment on issues.

### 4.8 Configuration model (maximum configurability)

**Principle:** onboarding a new project, changing a model, a threshold, a routing rule, a knowledge pack or a template must never require a code change or an image rebuild. All behaviour is described by one pydantic schema (`config/schema.py`) which is the single source of truth for validation, JSON Schema generation, defaults, docs and `explain` output.

**Layers (lowest → highest precedence):**
1. Built-in defaults (from the schema).
2. Deployment/org config: Helm `config:` values rendered into a ConfigMap (`squad.yaml`) plus env vars using the nested convention `SQUAD__SECTION__KEY` (e.g. `SQUAD__AGENTS__DWIGHT__MODEL`).
3. Project registry `projects.yaml` (ConfigMap or mounted directory; one file per project allowed): maps `project` keys and **glob patterns** (`group/*`, `acme/web-*`) to provider, `base_url`, secret references and overrides, with `extends: <profile>` and inheritance from the most specific matching entry. Named **profiles** (`strict`, `balanced`, `lenient`, user-defined) are reusable bundles of overrides.
4. Repository config `.squad/config.yml` (optionally `.squad/baseline.yml`), read from the **target branch** (never from the change request head unless explicitly allowed), validated and cached by SHA. Supports `extends: <profile>`.
5. Invocation payload `project_config.overrides` (caller-trusted, allow-listed subset).

**Merge rules:** deep merge; lists replace unless a field is annotated `mergeable_set`. Every field carries a merge policy in the schema (`org_only`, `tighten_only`, `free`). At layers 4 and 5, security-relevant fields are **tighten-only** or **org-only**: a project may lower blocker thresholds, enable more rules, add reviewers, shrink allow-lists and budgets, but may **not** enable writes when the org forces dry-run, add egress hosts, add tools or executables, disable rules marked as floor, raise budgets above the platform maximum (`limits.*`), change `vcs.base_url`, or reference secret names outside `secrets.allowed_patterns`. Violations are rejected, listed in the review summary, and the **whole repo layer is ignored** (never partially applied). An invalid repo config produces a warning note on the change request and falls back to the project/org layers. The effective-config hash is recorded in every result (`stats.config_hash`). Org and registry files are hot-reloaded (mtime watch or SIGHUP) without a restart; a bad reload keeps the previous good config and raises an alert metric.

**Configuration surface (all keys optional, all documented with defaults):**
- `vcs`: provider, base_url, auth (GitHub App id / installation id / private-key secret, or token secret), bot_username, status_mode (`check_run | commit_status | auto`), status_context_template, approve_mode, labels (names/colours), comment_style (`inline | summary | both`), protected_branches override.
- `trigger`: events handled, `on_push`, `allowed_commenters`, slash commands, debounce window, skip rules (draft change requests, labels such as `skip-squad`, WIP titles, bot authors).
- `agents.<id>`: `enabled`, `model` and `fallback_model` (aliases), `temperature`, `max_tokens`, `max_iterations`, budgets (tokens, wall-clock, tool calls, cost hint), `prompt_extra` (append-only guidance text, size-capped, treated as untrusted guidance, cannot override system rules), `knowledge_extra_dirs`, `tool_allowlist` (subset only), `severity_overrides` and `disabled_rules` per `rule_id` (floor rules are not disableable), `language` of comments.
- `routing` (michael): glob → agent table (extensible), risk-tier rules (sensitive path globs, size thresholds, dependency changes), always-run agents, specialist URLs, per-agent timeouts, fan-out concurrency, `specialists_post`.
- `review`: ignore globs (generated, vendored, lockfiles, snapshots), max diff size and chunking policy, `min_confidence_to_publish`, `min_severity_inline`, `max_findings`, verdict policy thresholds, summary template, suppression comments (`squad-ignore: <rule_id> <reason>`; a reason is mandatory, suppressions are listed in the summary), baseline file of accepted findings with mandatory expiry date.
- `skills`: paths, ref (`base | head`), limits, allowed sources.
- `security` (dwight): intel sources on/off, host allow-list (org-only), cache TTL, KEV/EPSS/CVSS thresholds for severity mapping, offline fail mode, accepted-risk list with expiry, local scanners on/off.
- `ops` (darryl): namespace allow-list, observability adapter endpoints (Prometheus, Loki, Argo CD), redaction patterns, log and query caps, incident-correlation window.
- `implementer` (pam): branch name template, commit message template, MR title/body templates, labels, reviewers, assignees, `mr_draft` (default `false`), check commands override, sandbox image and resource limits, git identity, protected paths the agent must not touch (default: CI files, lockfiles unless the task requires them), executable allow-list extension (org-only).
- `llm`: gateway URL, key secret reference, tag template (default first tag `squad:code-squad`, plus `project:<key>`, `agent:<id>`), per-project budget caps, alias map.
- `observability`: OTLP endpoint, sampling, `content_capture`, log level.
- `limits`: platform-wide hard ceilings that no lower layer can exceed.
- `secrets`: provider type, `allowed_patterns`.
- `extra_agents` (org layer only): declare additional specialists without code: `{id, description, prompt_path, knowledge_dirs, tool_preset: review_readonly | review_publish, model, routes}`. The platform registers them at startup; presets can never include `EXTERNAL_WRITE` tools other than `publish_review`. This lets a new language or concern (Python, Go, Terraform, accessibility) reuse the same runtime.

**CLI and introspection:** `squad config schema` (emits JSON Schema), `squad config validate <file|dir>`, `squad config explain <project> [--repo-config <path>] [--format yaml|json]` (effective config with **provenance per key**: which layer set it), `squad config init <react|java|generic>` (scaffolds `.squad/config.yml` with the schema hint line), and `squad review <target> --post false` for a safe trial. JSON Schemas are committed under `schemas/` and a test fails if they drift from the pydantic models.

---

## 5. Reviewer agents: jim (React) and angela (Java)

Each has: `prompt.md` (role, method, severity rubric, output rules), embedded `knowledge/` baseline, and tools:

- `get_review_context(change_request)` — one call returns change-request metadata, `head_sha`, immutable diff at that SHA, changed-file list with language/framework detection, pipeline status, existing discussions, project policy.
- `read_file(path, ref, range)`, `search_repo(pattern)`, `list_tree(path)` — read only, bounded output.
- `get_project_skills()` — returns the merged skill set (§6) already validated.
- `publish_review(findings, summary)` — `EXTERNAL_WRITE`, idempotent, respects dry-run.
- `finish(result)` — validated structured output.

**jim baseline knowledge** (`knowledge/react/*.md`, concise, dated, with the evidence a reviewer should cite): rules of hooks and effect hygiene (dependencies, cleanup, avoid effects for derived state, race conditions on fetch), state placement and server-state libraries, rendering performance (memoisation only with evidence, keys, list virtualisation, code splitting, bundle impact), React Server Components/Next.js caveats when present, TypeScript strictness (no `any` leaks, discriminated unions, narrowing), accessibility (semantic HTML, focus management, ARIA misuse, keyboard, labels), forms and validation, error boundaries and suspense, testing (Testing Library queries by role, avoiding implementation details, MSW, Playwright for e2e), security-adjacent items (XSS via `dangerouslySetInnerHTML`, URL handling, token storage), dependency hygiene and anti-patterns.

**angela baseline knowledge** (`knowledge/java/*.md`): null-safety and `Optional` use, immutability, equals/hashCode, resource handling (try-with-resources), concurrency (thread safety, `CompletableFuture`, virtual threads caveats, locking), exceptions (no swallowing, meaningful types, transactions), collections/streams misuse, Spring specifics when present (DI, `@Transactional` boundaries and self-invocation, bean scopes, validation, controller/DTO separation, N+1 and lazy loading in JPA, pagination), API design and backward compatibility, logging (no sensitive data, correct levels), testing (JUnit 5, Mockito misuse, Testcontainers, determinism), build hygiene (Maven/Gradle), performance pitfalls, and Java-version-aware advice (detect the project's target release from the build file and do not suggest features it cannot compile).

Both: detect framework/version from manifests (`package.json`, lockfile, `tsconfig.json`; `pom.xml`/`build.gradle*`) and tailor advice. Project skills **extend or override** the baseline conventions (naming, architecture rules, banned APIs) but can never lower the severity rubric below the security/correctness floor defined in the system prompt.

---

## 6. Runtime skills (hybrid)

**Skill format:** a directory (or payload entry) with `SKILL.md`: YAML frontmatter (`name`, `description`, optional `applies_to` globs, `agents` list, `priority`) followed by a markdown body. Reference format from the reference squad payload is `{name, description, body}`; support both.

**Sources and precedence (highest first):**
1. Payload `skills[]` (trusted caller decides).
2. Repository skills at `project_config.skills_repo_path` (default candidates, in order: `.agents/skills/`, `.claude/skills/`, `.squad/skills/`), read **from the base/target branch** of the MR by default, not from the MR's head, so an MR cannot silently rewrite its own review rules. Option `skills_ref: head` exists but is off by default and logs a warning; a change to skill files inside the MR is itself flagged in the summary.
3. Built-in baseline knowledge (§5).

**Rules:**
- Skills are *guidance*, never authority: they cannot add tools, change tool policy, alter output schema, toggle dry-run, or instruct the agent to ignore system rules. The loader strips/ignores such attempts and adds a warning.
- Limits (configurable): max 20 skills, 20 KB per skill, 80 KB total; oversize → truncated with warning, not silent.
- Progressive disclosure: only `name` + `description` go in the prompt; the body is fetched on demand through a `load_skill(name)` tool (`READ`), except skills marked `always: true`.
- Selection by `applies_to` globs against the changed files; cache by (project, ref SHA, path) with TTL.
- All skill bodies pass through `untrusted.py` wrapping; result lists which skills were applied (`stats.skills_applied`) for auditability.
- `pam` and `jim` share the same loader; `angela` uses it with Java-specific discovery defaults.

Tests: precedence, override rules, limits, base-branch reading, hostile skill content, glob selection, cache invalidation on SHA change.

---

## 7. dwight (sec-reviewer: security posture)

**Scope:** application code in any language present in the diff (primary focus JS/TS and Java), configuration, dependency manifests, Dockerfiles, CI files, IaC (deferring deep CI/IaC mechanics to `darryl` but flagging security issues), secrets exposure, authn/authz, input handling, crypto misuse, supply chain.

**Embedded guidelines** (`knowledge/security/*.md`, each file with source name, version/date and a "how to apply in review" section; keep them concise and checkable): OWASP Top 10 (current edition), OWASP API Security Top 10, OWASP ASVS (control families, levels), OWASP Top 10 for LLM applications (for AI-related code), CWE Top 25 (current list) with CWE ids for findings, secure-coding cheat sheets (injection, XSS, CSRF, SSRF, deserialisation, path traversal, authN/session, secrets, logging), CIS-style hardening for Docker and Kubernetes manifests, NIST SSDF and SLSA basics for supply chain, plus language packs: Node/React (prototype pollution, `dangerouslySetInnerHTML`, `postMessage`, localStorage tokens, npm install scripts) and Java (XXE, deserialisation, SpEL/OGNL injection, Spring Security misconfiguration, JNDI/Log4Shell class issues, SQL via string concat in JPQL/native queries). Each rule has a stable `rule_id`.

**Live intelligence tools** (all `READ`, all output treated as untrusted data, with cache, rate-limit/backoff, timeout, and egress via `EGRESS_PROXY_URL` if set):
- `parse_dependencies(ref)` — deterministic parser for `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `pom.xml` (resolved via effective versions when possible), `gradle.lockfile`/`build.gradle*`, `requirements*.txt`/`uv.lock`, `Dockerfile` base images; outputs a package list with ecosystem and exact version; flags unpinned versions.
- `lookup_vulnerabilities(packages[])` — OSV.dev batch query as the primary source (`/v1/querybatch`, then `/v1/vulns/{id}` for detail), GitHub Advisory Database as secondary.
- `lookup_cve(id)` — NVD CVE API 2.0 for CVSS/CWE/references; enrich with **CISA KEV** membership (known exploited) and **EPSS** score. Cache the KEV list and refresh periodically.
- `search_advisories(query, since)` — recent advisories for a given ecosystem/package/keyword, limited to the allow-listed hosts above.
- Hard allow-list of hosts; no arbitrary URL fetch tool. API keys (e.g. NVD) optional via `SecretProvider`.
- **Offline/restricted-egress mode:** if lookups fail, findings from them are marked `confidence: low` and the summary states "vulnerability data unavailable/unverified"; the verdict is never `approve` on missing data for a diff that touches dependencies.
- Optional local scanners if binaries exist in the image or sandbox (`gitleaks`, `semgrep`, `trivy fs`): wrap as `READ` tools running in the sandbox with a pinned rule set; their raw output is untrusted input to the model, and results are normalised to the Finding schema. Not required for acceptance, but design the tool interface so adding them is trivial.

**Method in the prompt:** build a short threat model of the change (entry points, trust boundaries, data sensitivity), check against the embedded rules, prefer exploitable findings with a concrete attack path over theoretical ones, map each to CWE (and CVE when dependency-based), include fix guidance, never print secrets found (redact, report location only), rank dependency findings by KEV > EPSS > CVSS > reachability evidence (is the vulnerable API actually used?).

---

## 8. darryl (devops: pipeline review + troubleshooting)

**Mode `review`** (MR): files of interest — `.gitlab-ci.yml` and includes, `.github/workflows/*.yml` and composite/reusable actions, Dockerfiles, compose, Helm charts, Kustomize, Terraform/OpenTofu, Kubernetes manifests, justfile/Makefile/scripts. Checklist: pipeline correctness and speed (caching, `needs`, `rules` vs `only/except`, artifacts, interruptible), reproducibility (pinned images/digests), secrets handling (masked/protected vars, no echo), least privilege (runners, tokens, `id_tokens`), image hygiene (multi-stage, non-root, minimal base, healthchecks, `.dockerignore`), K8s manifests (resources/limits, probes, securityContext, PodDisruptionBudget, topology spread, NetworkPolicy, rollout strategy), IaC (state handling, drift, blast radius, module pinning), release safety (rollback path, migrations, feature flags), and DORA impact (lead time, change failure risk, MTTR). Same Finding schema.

**Mode `troubleshoot`**: input is a symptom (alert text, ticket, "service X returns 5xx since 14:00"), optional namespace/workload/time window. Method (put in the prompt): restate the symptom and blast radius → form ranked hypotheses → gather evidence with read-only tools → confirm/refute → conclude with root cause *or* explicit "unknown, here is what to check next" → propose remediation steps and a rollback option → list what was *not* checked. Distinguish observed facts from inference. Never claim a cause without evidence.

**Troubleshooting tools (all `READ`, bounded and redacted):**
- Kubernetes (official Python client, in-cluster config, allow-listed namespaces): `k8s_get(kind, ns, name|selector)`, `k8s_describe`, `k8s_events(ns, window)`, `k8s_logs(pod, container, since, tail, previous)`, `k8s_top`, `rollout_history`. Secrets are never readable (the tool refuses kind `Secret`, and RBAC denies it).
- CI/CD through the provider interface (§4.7): GitLab pipelines/jobs or GitHub Actions workflow runs/jobs, job logs (trimmed to the failure region), environments and deployments, recent change requests merged before the incident ("what changed" correlation).
- Optional pluggable observability adapters behind interfaces, enabled by config only: Prometheus/PromQL (`instant`/`range` query with step and result-size caps), Loki/LogQL, Argo CD/Flux status, Alertmanager. Provide the interfaces, a working Prometheus adapter, and fakes for tests; others may be stubs that return a clear "not configured".
- `redact(text)` applied to every tool output (tokens, passwords, keys, emails optional, connection strings).
- Helm chart ships a `ClusterRole`/`Role` for read-only access with a values flag listing allowed namespaces; document that the darryl pod must run with its own ServiceAccount.

**No cluster mutation tools exist.** Remediation is advice only. Any external write is limited to MR/issue comments through the posting gate.

---

## 9. pam (frontend-dev: senior React engineer)

**Modes:** `advisor` (default; read-only on the repo, answers design/pattern questions, produces plans and snippets) and `implementer` (enabled per invocation with `mode: "implementer"`. There is **no human approval gate** (no plan approval, no confirmation step): the agent plans, implements, pushes and opens the MR in a single invocation. Humans review the MR through the normal merge-request process; the agent never merges).

**Embedded expertise** (`knowledge/react/*.md`, shared with `jim` through a common package so both stay consistent): component design and composition, hooks and custom hooks, state management choices (local vs context vs store vs server-state), data fetching and caching, forms, routing, TypeScript patterns, performance profiling methodology, accessibility, design-system usage, testing pyramid (unit/component/e2e), error handling, folder structure and module boundaries, migration playbooks (class → function components, CRA → Vite, React version upgrades) — each marked with the React/tooling version it was written for. Project conventions come from runtime skills (§6) and from reading the repo (existing patterns win over generic preference).

**Implementer workflow:** 1) read task and acceptance criteria, 2) explore the repo (read-only tools) and load skills, 3) write a short plan (files to touch, tests to add), 4) create branch `pam/<task-key>-<slug>` in the sandbox clone, 5) implement in small steps, 6) run the repo's own checks (detect from `package.json` scripts: lint, typecheck, test, build; prefer a `just`/`make` target if present), 7) fix until green or report precisely what fails, 8) commit (conventional message, git identity from config), push, open the MR with description (what/why/how tested/risks); `implementer.mr_draft` (boolean, default `false`, §4.8) lets a project opt into draft MRs, but nothing blocks on a human before creation, 9) return the result with the MR URL. Never push to protected branches, never force-push, never merge, never modify CI config or lockfiles unless the task requires it (and then say so in the MR).

**Sandbox (`_common/sandbox/`):**
- Interface `Sandbox`: `clone(repo, ref)`, `exec(cmd, timeout, env_allowlist)`, `read/write/apply_patch`, `diff()`, `destroy()`. Command execution is an allow-list of executables (`git`, `node`, `npm`, `pnpm`, `yarn`, `npx` for local binaries, `tsc`, `vitest`, `jest`, `eslint`, `prettier`, `just`, `make`) plus package-script invocations; no shell metacharacter composition; no access to agent secrets; output size-capped.
- `LocalProcessSandbox` (dev and tests): temp dir, scrubbed environment, resource limits via `resource`/timeouts.
- `KubernetesJobSandbox` (default in cluster): one ephemeral Pod/Job per invocation from `sandbox-node` image (non-root, read-only root fs except workspace `emptyDir`, resource limits, `activeDeadlineSeconds`, `ttlSecondsAfterFinished`), exec via the Kubernetes API, destroyed in a `finally`. The agent ServiceAccount gets a minimal `Role` (create/get/delete/exec pods only in the sandbox namespace). A `NetworkPolicy` allows egress only to the git host and the package registry/proxy (configurable). Document the ADR with the alternative considered (sidecar with shared volume: simpler, weaker per-invocation isolation).
- Credentials for git push are injected only into the git helper process, scoped to the repo, never into npm scripts.
- Trajectory monitor and audit telemetry: record every command (argv, exit code, duration, truncated output hash), detect loops (same command/failure ≥ 3 times), enforce wall-clock, command-count and token budgets; on breach stop and return `incomplete` with a clear reason.

---

## 10. michael (orchestrator)

**Responsibilities:** receive a trigger (webhook, API, CLI), identify intent (`mr_review`, `incident`, `implement`, `question`), pick specialists, run them **in parallel** with per-agent timeouts, aggregate, publish one consolidated outcome.

**Deterministic routing first** (unit-tested table): changed-file globs and manifests → `jim` (`*.tsx|jsx|ts|js` with React deps), `angela` (`*.java|kt`, `pom.xml`, `build.gradle*`), `darryl` (CI/Docker/IaC/K8s files), `dwight` (always, scaled by risk tier). A cheap LLM call classifies only when intent or stack is ambiguous. Intent `incident` → `darryl` in troubleshoot mode; `implement` → `pam`.

**Risk tier** (deterministic): from diff size, sensitive paths (auth, payments, infra, CI), dependency changes, and presence of secrets-like patterns → `low|medium|high`; high tier forces `dwight` full scope and requires stricter verdict thresholds.

**Fan-out:** call specialists over HTTP using service DNS (`http://code-squad-<agent>.<ns>.svc:8080`) or `ORCHESTRATOR_SPECIALIST_URLS`; always pass `post: false` to specialists (they return findings only) and let the orchestrator publish, so there is exactly one publication path and one summary. Provide a flag `specialists_post: true` for standalone-compatible behaviour. Circuit-breaker and retry with idempotency keys; forward trace context.

**Aggregation:** merge findings, deduplicate across agents (same file/line/overlapping rationale → keep highest severity, list contributing agents), order by severity, produce one summary (what was reviewed, which agents ran, which failed/timed out, risk tier, top issues, verdict). **Any specialist failure or timeout makes the verdict `incomplete`** and says so explicitly; the commit status is `pending`/`failed` accordingly, never `success`.

**Everything above is configuration-driven** (§4.8 `routing`, `review`, `agents.*`): routing table, risk-tier rules, thresholds, timeouts and enabled agents come from the effective config of the project, and `extra_agents` are routed like built-in ones.

**Verdict policy** (configurable per project): any `blocker` → `request_changes`; majors above threshold → `comment` with warning; otherwise `approve`. The squad never merges; approval is a signal only.

---

## 11. Prompts

Each `prompt.md` (English) contains: role and boundaries; the untrusted-content rule; method; severity rubric and what *not* to flag (style nits already enforced by linters, speculative issues without evidence); output contract (must end with `finish()`); dry-run awareness; how to use skills and tools economically; explicit statement of limits ("if you cannot verify, say so and lower confidence"). Keep prompts under ~2,500 words each; move reference material to `knowledge/` and expose it through a `read_knowledge(topic)` tool (`READ`) with a short index in the prompt, so context stays lean. Add `scripts/check_prompts.py` (word count, required sections present) and run it in `just check`.

---

## 12. Kubernetes and delivery

- `deploy/Dockerfile`: multi-stage, `python:3.12-slim`, `uv sync --frozen`, non-root UID, no build tools in the final stage, `tini` or equivalent, `HEALTHCHECK`, `EXPOSE 8080`, `ENTRYPOINT` runs `uvicorn code_squad.server:app`. Build with `docker buildx` for `linux/amd64,linux/arm64`; tag = short SHA (+ semver on release). `sandbox-node.Dockerfile` for the sandbox pods (node LTS, git, pnpm/yarn via corepack, no secrets).
- **Helm chart** `deploy/helm/code-squad`: one Deployment + Service per enabled agent from the same image (`AGENT_NAME` set per Deployment), values for image, resources, replicas, HPA (optional), env, secret refs (`existingSecret`), ConfigMap for non-secret settings, `serviceAccount` per agent, RBAC templates (devops read-only, pam sandbox), `NetworkPolicy` templates (default deny egress, allow LLM gateway, VCS host, OSV/NVD/GHSA/KEV/EPSS hosts for `dwight`, DNS, OTLP collector), `PodDisruptionBudget`, `securityContext` (runAsNonRoot, readOnlyRootFilesystem, drop ALL caps, seccomp RuntimeDefault), probes on `/ping` and `/ready`, optional `ServiceMonitor`, optional Ingress for the orchestrator webhook endpoints only (`/webhooks/gitlab`, `/webhooks/github`), `config.org` and `config.projects` values rendered into ConfigMaps (and mounted for hot reload), per-provider secret refs (GitHub App private key, GitLab token, webhook secrets) via `existingSecret`, with examples for External Secrets. Must pass `helm lint`, `helm template | kubeconform --strict`, and pod-security "restricted" checks.
- Local: `compose.yaml` (all agents + a fake LiteLLM stub for offline demo) and `deploy/kind/` script that creates a kind cluster, loads the image, installs the chart with test values, and runs the smoke test.
- CI for this repository: provide **both** `.gitlab-ci.yml` and `.github/workflows/ci.yml` with the same stages: lint → typecheck → test → docs → build (buildx multi-arch) → chart-lint → (manual) deploy. Both call `just check` so the gate is identical. Consumer-side snippets (projects calling michael on change-request events) are in §17.
- `justfile`: `check`, `test`, `lint`, `typecheck`, `docs`, `build`, `run-local <agent>`, `invoke <agent> "..."`, `kind-up`, `kind-smoke`, `helm-lint`, `eval`.
- Backstage: `catalog-info.yaml` (Component + API per agent, owner group configurable) and TechDocs via mkdocs (`mkdocs build --strict` in the gate).

---

## 13. Evaluation and tests

**Unit/integration (pytest, no network):** fake model provider that replays scripted tool-call sequences (build this early; it makes everything else testable), fake VCS provider (plus recorded-HTTP fixtures for GitLab and GitHub), fake OSV/NVD/KEV/EPSS responses, fake Kubernetes client, fake sandbox. Cover: payload validation (fail-closed, unknown keys, wrong `post` type, foreign input key), tool policy registry, dry-run for every `EXTERNAL_WRITE` tool, finding anchoring/staleness/dedup/idempotent re-publish, skills (§6 tests), untrusted-content adversarial cases (§4.5), truncation and iteration-limit handling, orchestrator routing table and partial-failure verdict, sandbox command allow-list and cleanup-on-error, redaction, secret-provider behaviour, Helm values rendering.

**Eval (`eval/`, live-LLM runs gated by env, never in default `just check`):** small fixture repos — a React/TypeScript app and a Spring app — each with *seeded* defects (known bug classes, known vulnerable dependency versions, a leaked fake secret, a pipeline anti-pattern, a prompt-injection string in a file). Golden cases list expected findings (file, line range, category). Scorers compute recall of seeded issues, precision against a "must-not-flag" list, false-blocker rate, and injection resistance; output a markdown report. Include a devops troubleshooting scenario replayed from recorded fake cluster state (CrashLoopBackOff from bad env var; OOMKilled; failed rollout due to image pull error) scoring root-cause correctness. Include a pam scenario (add a small feature to the fixture app; must pass lint/typecheck/tests and produce a change request on the fake VCS without any approval step).

---

## 14. Milestones and acceptance criteria

| # | Milestone | Done when |
|---|---|---|
| M0 | Repo bootstrap | `pyproject`, `uv.lock`, layout, `justfile`, ruff/mypy/pytest wired, `AGENTS.md` conventions, `STATUS.md`, ADR 0001 (stack), CI file; `just check` green on an empty skeleton |
| M1 | Platform core | `AgentSpec`, registry, contract models, validation, tool policy, posting gate, untrusted wrapper, fake model provider, `runtime.run_task` with finish/retry/truncation/iteration handling, FastAPI server with `/ping`, `/ready`, `/metrics`, `/invocations`; tests for all of the above |
| M2 | VCS providers + findings pipeline | `VcsProvider` with **GitLab and GitHub** implementations (REST via httpx, GitHub App auth + PAT fallback), `IssueTracker` interface, review-context tool, anchoring/validation/dedup/idempotent publish, status/check publication with capability fallback, webhook verification for both; the shared conformance suite passes for the fake, GitLab and GitHub providers |
| M3 | Configuration system | Schema, layering, tighten-only merge, project registry with glob inheritance, repo config from base branch, profiles, `extra_agents`, hot reload, `squad config schema/validate/explain/init`, committed JSON Schemas with sync test; full unit tests of merge/provenance/security rules |
| M4 | Skills system | Loader, discovery, precedence, limits, base-branch reading, `load_skill`, caching; adversarial tests |
| M5 | jim + angela | Prompts, knowledge packs, tools wired, scripted-model tests pass, eval fixtures created, `check_prompts` green |
| M6 | dwight | Knowledge pack, dependency parsers (all listed lockfile types, with fixtures), OSV/NVD/GHSA/KEV/EPSS clients with cache/backoff/allow-list, offline mode behaviour, tests with recorded responses |
| M7 | darryl (devops) | Review checklist + tools, troubleshooting tools with redaction and read-only guarantees, Prometheus adapter, RBAC templates, scenario tests |
| M8 | Sandbox + pam | Sandbox interface, local and Kubernetes-Job implementations (K8s one tested against fake client; verified on kind in M10), implementer + advisor modes, autonomous end-to-end flow (no approval gate), trajectory monitor, MR creation on fake VCS |
| M9 | Orchestrator | Routing table, risk tier, webhook, fan-out with timeouts/circuit-breaker, aggregation/dedup, consolidated publication, partial-failure semantics, optional async jobs |
| M10 | Packaging & K8s | Multi-arch Dockerfiles, Helm chart, NetworkPolicies, RBAC, compose, kind script; `kind-smoke` deploys everything with the fake LLM stub and exercises each agent end to end |
| M11 | Observability, docs, examples, eval | OTLP traces + Prometheus metrics verified; the **complete documentation set of §16** with generated reference pages and validated examples; every artifact of §17 present and validated; Backstage catalog; eval reports generated; `docs/HANDOFF.md` |

---

## 15. Final validation (must all pass before you stop)

1. `just check` green (ruff, mypy strict, pytest, prompt checks, `mkdocs build --strict`, `helm lint`, kubeconform).
2. `docker buildx build --platform linux/amd64,linux/arm64` succeeds (if buildx or emulation is unavailable, build native arch and record the limitation in `HANDOFF.md`).
3. `just kind-smoke` passes on a local kind cluster, or, if kind is unavailable in the environment, `helm template` renders for default and hardened values and `docker compose` smoke passes; record which path was used.
4. Every agent answers a scripted invocation end to end through HTTP with the fake model; dry-run produces zero external writes; a hostile-content fixture does not change any verdict.
5. The VCS conformance suite is green for fake, GitLab and GitHub providers; `squad config validate` passes on every file under `examples/`; generated docs (config reference, env table, tool-policy table, capability matrix) have no drift (`just docs-gen --check`); every YAML/JSON block in `docs/` marked for validation is validated by tests.
6. No secrets or tokens in the repo (run a secret scan with a lightweight local pattern check at minimum).
7. `STATUS.md` shows all milestones done; `docs/HANDOFF.md` lists open limitations honestly (e.g. live-LLM eval results if they could not be run).

---

## 16. Documentation to write

All documentation lives in `docs/`, is built with `mkdocs build --strict` (TechDocs-compatible), is written for operators and project teams (not only for developers), and contains **verified examples**: YAML/JSON blocks marked `<!-- validate: config|invocation|helm-values -->` are extracted and validated by `tests/test_docs_examples.py`. Reference pages are **generated** (`scripts/gen_docs.py`, `just docs-gen`, drift checked with `--check` in `just check`): configuration reference from the pydantic schema, environment-variable table, tool-policy table (tool → agent → class), VCS capability matrix, agent model/budget defaults.

Required pages:

1. `index.md` / `README.md` — what the squad is, the six agents and their roles, 10-minute quick start (docker compose + fake LLM), links.
2. `architecture/` — overview and Mermaid diagrams: component view, sequence of a change-request review (webhook → michael → specialists → consolidated publication), sequence of `pam` (task → sandbox → MR), config layering, deployment topology on Kubernetes, trust boundaries; request/response contract; finding schema; failure semantics (`incomplete`).
3. `agents/<id>.md` (one per agent, six pages + `extra-agents.md`) — purpose, triggers, modes, inputs, tools with policy class, outputs with a real sample, embedded knowledge packs and how to extend them, every config key that affects it with defaults, limits, known weaknesses, how to evaluate it.
4. `configuration/` — concepts (layers, tighten-only, provenance, profiles, glob inheritance), **generated reference**, recipes (strict profile for payments code, lenient profile for prototypes, swap a model per agent, disable one agent, add a routing rule, ignore generated code, baseline accepted findings, add a language with `extra_agents`, per-project LLM budget).
5. `vcs/gitlab.md` and `vcs/github.md` — creating the bot identity, exact token scopes / GitHub App permissions and webhook events, webhook setup with secret, CI/Actions snippets, self-managed/GHES notes, capability matrix and fallbacks, rate-limit behaviour, troubleshooting; `vcs/adding-a-provider.md`.
6. `onboarding/new-project.md` — a copy-paste checklist (register project or rely on a glob, install webhook or CI snippet, add `.squad/config.yml`, add skills, dry-run trial with `post:false`, go live), plus `onboarding/skills-authoring.md` (format, discovery, precedence, examples for React and Java, how to test a skill) and `onboarding/knowledge-packs.md`.
7. `deployment/` — Helm values reference with example values files, secrets management (plain Secrets, External Secrets/Sealed Secrets), network policies and egress (LLM gateway, VCS, advisory hosts, proxy / air-gapped setup), RBAC (devops read-only, sandbox), ingress for webhooks, scaling and HA, upgrade and rollback, multi-arch images, kind/compose local environments.
8. `operations/runbook.md` — dashboards and suggested alerts, metrics glossary, cost tracking via LiteLLM tags, common failures and fixes (gateway down, rate limits, webhook not firing, stale or invalid config, sandbox pod stuck, advisory source unreachable, comment duplication), log fields, how to replay an invocation in dry-run, incident checklist.
9. `security/` — threat model (assets, trust boundaries, adversaries), untrusted-content and prompt-injection mitigations, tool-policy table, secrets handling, RBAC and sandbox isolation, data retention (what is and is not stored), residual risks, hardening checklist, vulnerability reporting.
10. `testing/` — unit/integration strategy, fake model provider usage, conformance suite, eval fixtures and scorers, how to add a golden case, how to read the eval report.
11. `contributing/` — `AGENTS.md` conventions, adding an agent, adding a tool and classifying it, adding a VCS provider, adding a knowledge pack, ADR process, release and versioning.
12. `decisions/` — ADRs: stack (Strands + FastAPI), VCS abstraction, configuration layering and tighten-only, skills read from base branch, sandbox backend choice, no approval gate for `pam` and what compensates for it, agent naming.
13. `CHANGELOG.md`, `docs/HANDOFF.md`, `docs/faq.md`.

---

## 17. Configuration artifacts to ship

Everything below must exist, be annotated with comments explaining each key, carry the schema hint line (`# yaml-language-server: $schema=...`) and be validated by `squad config validate` / `helm lint` / tests.

- `schemas/`: `squad-config.schema.json`, `invocation.schema.json`, `finding.schema.json`, `projects.schema.json` (generated, committed, sync-tested).
- `examples/org/`: `squad.yaml` (annotated org defaults), `projects.yaml` (a GitLab project, a GitHub project, a glob group, a GHES example), `profiles/strict.yaml`, `balanced.yaml`, `lenient.yaml`, `extra-agents.yaml` (a Python reviewer defined purely by config).
- `examples/repo/`: `.squad/config.yml` for a React app and for a Java/Spring service, `.squad/baseline.yml`, example skills (`.agents/skills/<name>/SKILL.md`) for React and Java including one with `applies_to` globs.
- `examples/gitlab/`: `gitlab-ci-snippet.yml` (job calling michael on merge request events, `post` toggle), webhook setup notes, required token scopes.
- `examples/github/`: `github-actions-workflow.yml` (`pull_request` trigger calling michael), `github-app-manifest.json` (minimum permissions: metadata read, contents read/write only if `pam` is used, pull requests write, issues write, checks write, commit statuses write, actions read; webhook events for pull request, issue comment, pull request review comment and, if used, issues), notes for GHES.
- `deploy/helm/code-squad/values.yaml` plus `deploy/helm/code-squad/values-examples/`: `minimal-kind.yaml`, `gitlab-only.yaml`, `github-app.yaml`, `multi-provider.yaml`, `production-ha.yaml`, `egress-proxy-airgapped.yaml`, `external-secrets.yaml`.
- `.env.example` covering every bootstrap env var (generated from the schema), `compose.yaml` and a fake-LLM stub config.
- Secrets examples: Secret manifests with placeholders, External Secrets / Sealed Secrets samples (no real values).
- Observability: Prometheus alert rules and a Grafana dashboard JSON (invocations, latency, findings, tokens/cost hints, tool calls by class, VCS errors, config reload failures).
- `catalog-info.yaml` for Backstage (Component + API per agent, TechDocs annotation).
- `scripts/`: `gen_docs.py`, `gen_schemas.py`, `check_prompts.py`, `smoke_test.sh`, `bump_image.py`.

---

## 18. Explicit non-goals

No automatic merging; no cluster mutation by any agent; no storage of source code or model outputs beyond the invocation (except cached public advisory data and optional session store); no UI; no VCS providers beyond GitLab and GitHub in this version (the interface and conformance suite make adding others straightforward); no multi-tenant auth beyond a shared bearer token or mTLS at the ingress (document how to put the services behind the existing identity layer); no custom model hosting.

---

## Addendum (from the requester)

- The default branch of the repository is `main`.
- The solution architect designs and reviews; implementation of each milestone is delegated to sub-agents whose work is reviewed before commit.
