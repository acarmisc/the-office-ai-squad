<!-- generated — do not edit. Source: scripts/gen_docs.py. Regenerate with: just docs-gen -->

# Configuration reference

Generated from `code_squad/_common/config/schema.py`. Every key is optional
unless the table says `required`, and every table shows the built-in default.
Merge policies: `free` (any layer may set it), `tighten_only` (a repository or
call may only move it toward stricter), `org_only` (only the organisation file
or the project registry may set it). Concepts are explained in
[Configuration concepts](../configuration/concepts.md).

## File kinds

| File | Model | Notes |
| --- | --- | --- |
| Organisation file (`squad.yaml`) | `SquadConfig` | Full schema, org_only keys allowed. |
| Project registry (`projects.yaml`) | `ProjectsFile` and `ProjectEntry` | Matches, provider and secret names, `extends`, `overrides`. |
| Repository file (`.squad/config.yml`) | `RepoConfig` | Same keys as the organisation file plus `extends`. org_only keys are rejected. |
| Accepted findings (`.squad/baseline.yml`) | `Baseline` | Each entry needs an expiry date. Not applied at run time yet. |

## Organisation and repository keys

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `vcs` | section, see `vcs` | nested defaults | free |  | Version control settings. |
| `trigger` | section, see `trigger` | nested defaults | free |  | When and from whom reviews start. |
| `agents` | map of sections, see `agents.{key}` | nested defaults | free |  | Per-agent settings keyed by agent id. |
| `routing` | section, see `routing` | nested defaults | free |  | Routing, risk tiers and fan-out. |
| `review` | section, see `review` | nested defaults | free |  | Review policy. |
| `skills` | section, see `skills` | nested defaults | free |  | Runtime skill loading. |
| `security` | section, see `security` | nested defaults | free |  | Vulnerability intelligence and accepted risks. |
| `ops` | section, see `ops` | nested defaults | free |  | Operations (darryl) settings. |
| `implementer` | section, see `implementer` | nested defaults | free |  | Implementation settings (pam). |
| `llm` | section, see `llm` | nested defaults | free |  | LLM gateway settings. |
| `observability` | section, see `observability` | nested defaults | free |  | Tracing, logging and content capture. |
| `limits` | section, see `limits` | nested defaults | org_only |  | Platform ceilings no lower layer can exceed. Org-only. |
| `secrets` | section, see `secrets` | nested defaults | org_only |  | Secret provider and allowed names. Org-only. |
| `posting` | section, see `posting` | nested defaults | free |  | External write policy. |
| `repo_config` | section, see `repo_config` | nested defaults | free |  | Where repository config is read from. |
| `extra_agents` | list of sections, see `extra_agents[]` | nested defaults | org_only |  | Additional agents declared in configuration. Org-only. |

## `vcs`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `provider` | one of `gitlab`, `github`, `auto` | `"auto"` | org_only |  | VCS provider. 'auto' infers it from base_url for github.com and gitlab.com. Org-only: set it in the org config or the project registry. |
| `base_url` | string or null | `null` | org_only |  | API base URL for self-managed or enterprise hosts. Org-only. |
| `auth` | section, see `vcs.auth` | nested defaults | org_only |  | Credentials as secret names, matched against secrets.allowed_patterns. |
| `bot_username` | string or null | `null` | free |  | Login of the bot identity, used for loop prevention. |
| `status_mode` | one of `check_run`, `commit_status`, `auto` | `"auto"` | free |  | How verdicts are published. 'auto' prefers check runs and falls back. |
| `status_context_template` | string | `"ai-review/{agent}"` | free | max length 128 | Commit status or check name template; {agent} is the agent id. |
| `approve_mode` | one of `none`, `comment`, `approve` | `"none"` | tighten_only, tighten le, order none, comment, approve |  | Whether a positive verdict may approve the change request. Can only become stricter below the org layer (none &lt; comment &lt; approve). |
| `labels` | map of string to string | `{}` | free |  | Label name overrides, keyed by logical label name. |
| `comment_style` | one of `inline`, `summary`, `both` | `"both"` | free |  | Publish inline discussions, a summary note, or both. |
| `protected_branches` | list of string | `[]` | free, mergeable set (union) |  | Branches the squad must never write to. Lower layers may only add. |

### `vcs.auth`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `token_secret` | string or null | `null` | free, secret name | pattern ^[a-z0-9][a-z0-9._-]{0,252}$ | Secret name holding the VCS access token. |
| `app_id` | integer or null | `null` | free | &gt;= 1 | GitHub App id (numeric). |
| `installation_id` | integer or null | `null` | free | &gt;= 1 | GitHub App installation id (numeric). |
| `private_key_secret` | string or null | `null` | free, secret name | pattern ^[a-z0-9][a-z0-9._-]{0,252}$ | Secret name holding the GitHub App private key (PEM). |

## `trigger`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `events` | list of one of `change_request_opened`, `change_request_updated`, `change_request_ready`, `review_requested`, `comment`, `issue_assigned` | `["change_request_opened", "change_request_ready", "review_requested", "comment", "issue_assigned"]` | free |  | Events that start a review. |
| `on_push` | boolean | `false` | free |  | Also react to new pushes (change_request_updated). |
| `allowed_commenters` | list of string | `[]` | tighten_only, tighten subset |  | Users whose comments may trigger the squad. Empty means nobody. Lower layers may only shrink the list. |
| `slash_commands` | list of string | `["review", "sec", "implement", "help"]` | free |  | Slash commands recognised in comments, without the slash. |
| `debounce_seconds` | integer | `30` | free | &gt;= 0, &lt;= 3600 | Quiet period before a burst of events starts one run. |
| `skip_draft` | boolean | `true` | free |  | Skip draft change requests. |
| `skip_labels` | list of string | `["skip-squad"]` | free |  | Change requests carrying any of these labels are skipped. |
| `skip_wip_titles` | boolean | `true` | free |  | Skip change requests whose title starts with WIP or Draft. |
| `skip_bot_authors` | boolean | `true` | free |  | Skip change requests and comments authored by bots. |

### `agents.{key}`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `enabled` | boolean | `true` | free |  | Whether this agent runs at all. |
| `model` | string or null | `null` | free | pattern ^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$ | Model alias for this agent. Defaults to the agent's built-in alias. |
| `fallback_model` | string or null | `null` | free | pattern ^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$ | Model alias used once after a truncation or overload. |
| `temperature` | number or null | `null` | free | &gt;= 0, &lt;= 1 | Sampling temperature between 0 and 1. |
| `max_tokens` | integer or null | `null` | tighten_only, capped by limits.max_tokens | &gt;= 1 | Model output token cap per call. Cannot exceed limits.max_tokens. |
| `max_iterations` | integer or null | `null` | tighten_only, capped by limits.max_iterations | &gt;= 1 | Model turns per invocation. Cannot exceed limits.max_iterations. |
| `budgets` | section, see `agents.{key}.budgets` | nested defaults | free |  | Per-invocation budgets. Each is capped by the matching limits.* value. |
| `prompt_extra` | string or null | `null` | tighten_only, capped by limits.max_prompt_extra_chars | max length 20000 | Extra guidance appended to the agent prompt. Untrusted guidance: it cannot override system rules. Length is capped by limits.max_prompt_extra_chars. |
| `knowledge_extra_dirs` | list of string | `[]` | org_only |  | Additional knowledge directories the agent may read. Org-only. |
| `tool_allowlist` | list of string or null | `null` | tighten_only, tighten subset, tool names |  | Restrict the agent to these tools. Lower layers may only pick a subset of the base list; null means the agent's full tool set. External-write tools cannot be listed below the org layer. |
| `severity_overrides` | map of string to one of `blocker`, `major`, `minor`, `nit` | `{}` | free, floor rules |  | Severity per rule_id. Floor rules must stay at blocker. |
| `disabled_rules` | list of string | `[]` | free, mergeable set (union), floor rules |  | Rule ids turned off for this agent. Floor rules cannot be disabled. |
| `language` | string | `"en"` | free | min length 2, max length 16 | Language of published comments. |

### `agents.{key}.budgets`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `tokens` | integer | `100000` | tighten_only, capped by limits.max_tokens | &gt;= 1 | Maximum model tokens per invocation for this agent. |
| `wall_clock_seconds` | integer | `900` | tighten_only, capped by limits.max_wall_clock_seconds | &gt;= 1 | Maximum wall-clock seconds per invocation. |
| `tool_calls` | integer | `100` | tighten_only, capped by limits.max_tool_calls | &gt;= 1 | Maximum tool calls per invocation. |
| `cost_hint_usd` | number or null | `5.0` | free | &gt;= 0 | Advisory cost ceiling reported in stats.cost_hint. |

## `routing`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `routes` | list of sections, see `routing.routes[]` | nested defaults | free, mergeable set (union) |  | Changed-file glob to agent table. Lower layers may only add routes. |
| `sensitive_paths` | list of string | `["**/auth/**", "**/payment*/**", "**/security/**", "infra/**", ".gitlab-ci.yml", ".github/workflows/**", "**/Dockerfi...` | free, mergeable set (union) |  | Paths that raise the risk tier. Lower layers may only add patterns. |
| `size_thresholds` | section, see `routing.size_thresholds` | nested defaults | tighten_only |  | Changed-line thresholds for the risk tier. Lower layers may only lower them. |
| `always_run` | list of string | `["dwight"]` | free, mergeable set (union) |  | Agents that run on every review. Lower layers may only add agents. |
| `specialist_urls` | map of string to string | `{}` | org_only |  | Base URL per specialist agent for HTTP fan-out. Org-only. |
| `timeouts_seconds` | map of string to integer | `{"default": 600}` | free |  | Seconds per specialist call. The key 'default' applies to unlisted agents. |
| `fan_out_concurrency` | integer | `4` | free | &gt;= 1, &lt;= 32 | Specialists called in parallel. |
| `specialists_post` | boolean | `false` | tighten_only, tighten false |  | Let specialists publish directly instead of returning findings to michael. Lower layers may only keep it false. |

### `routing.routes[]`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `glob` | string | required | free | min length 1, max length 256 | Changed-file glob. '**' crosses directories, '*' does not. |
| `agents` | list of string | required | free | min length 1 | Agents to run when the glob matches. |
| `requires` | list of string | `[]` | free |  | Manifest hints the repository must satisfy, for example 'react'. |

### `routing.size_thresholds`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `medium` | integer | `300` | tighten_only, tighten le | &gt;= 1 | Changed lines at or above which the risk tier is medium. |
| `high` | integer | `1000` | tighten_only, tighten le | &gt;= 1 | Changed lines at or above which the risk tier is high. |

## `review`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `ignore_globs` | list of string | `["**/package-lock.json", "**/pnpm-lock.yaml", "**/yarn.lock", "**/poetry.lock", "**/Cargo.lock", "dist/**", "build/**...` | free, mergeable set (union) |  | Files excluded from review: generated, vendored, lockfiles, snapshots. Lower layers may only add globs. |
| `max_diff_bytes` | integer | `400000` | free | &gt;= 1000 | Diffs larger than this are chunked or truncated. |
| `chunking` | one of `split_by_file`, `truncate` | `"split_by_file"` | free |  | How oversized diffs are handled. |
| `min_confidence_to_publish` | one of `low`, `medium`, `high` | `"medium"` | free |  | Findings below this confidence are not published. |
| `min_severity_inline` | one of `nit`, `minor`, `major`, `blocker` | `"minor"` | free |  | Findings below this severity are summarised, not posted inline. |
| `max_findings` | integer | `30` | free | &gt;= 1, &lt;= 500 | Maximum findings published per run. |
| `verdict` | section, see `review.verdict` | nested defaults | free |  | Verdict thresholds. |
| `summary_template` | string or null | `null` | free | max length 8000 | Summary note template; null uses the built-in template. |
| `suppressions_enabled` | boolean | `true` | free |  | Honour in-code suppression comments (squad-ignore &lt;rule_id&gt; &lt;reason&gt;). |
| `baseline_file` | string | `".squad/baseline.yml"` | free | min length 1, max length 256 | Repository file with accepted findings and mandatory expiry dates. |

### `review.verdict`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `major_threshold` | integer | `1` | free | &gt;= 0 | Number of major findings at or above which the verdict becomes 'comment' instead of 'approve' (default 1: any major prevents approve). |
| `request_changes_on_blocker` | boolean | `true` | tighten_only, tighten true |  | A blocker finding requests changes. Lower layers cannot turn it off. |

## `skills`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `paths` | list of string | `[".agents/skills", ".claude/skills", ".squad/skills"]` | free |  | Candidate skill directories in precedence order. |
| `ref` | one of `base`, `head` | `"base"` | org_only |  | Branch skills are read from. 'head' lets a change request edit its own review rules, so it is org-only. |
| `max_skills` | integer | `20` | tighten_only, capped by limits.max_skills | &gt;= 1 | Maximum skills loaded per run. |
| `max_skill_bytes` | integer | `20480` | tighten_only, capped by limits.max_skill_bytes | &gt;= 1 | Maximum bytes per skill body; larger bodies are truncated with a warning. |
| `max_total_bytes` | integer | `81920` | tighten_only, capped by limits.max_total_skill_bytes | &gt;= 1 | Maximum total skill bytes per run. |
| `allowed_sources` | list of one of `payload`, `repo`, `builtin` | `["payload", "repo", "builtin"]` | tighten_only, tighten subset |  | Skill sources in use. Lower layers may only pick a subset. |

## `security`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `sources` | section, see `security.sources` | nested defaults | free |  | Intelligence sources switched on. |
| `allowed_hosts` | list of string | `["api.osv.dev", "services.nvd.nist.gov", "api.github.com", "www.cisa.gov", "api.first.org"]` | org_only |  | Hosts intelligence clients may contact. Org-only. |
| `cache_ttl_seconds` | integer | `21600` | free | &gt;= 0 | Advisory cache lifetime. |
| `severity_mapping` | section, see `security.severity_mapping` | nested defaults | free |  | Thresholds mapping advisory data to severity. Lower layers may only lower the numeric thresholds. |
| `offline_mode` | one of `fail_incomplete`, `low_confidence` | `"low_confidence"` | free |  | When advisory sources are unreachable: mark the run incomplete, or keep going with low-confidence findings. |
| `accepted_risks` | list of sections, see `security.accepted_risks[]` | nested defaults | free, mergeable set (union) |  | Accepted advisories. Expired entries are ignored with a warning. Lower layers may only add entries. |
| `local_scanners` | section, see `security.local_scanners` | nested defaults | free |  | Local scanners run in the sandbox when their binaries exist. |

### `security.sources`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `osv` | boolean | `true` | free |  | Query OSV for known vulnerabilities. |
| `nvd` | boolean | `true` | free |  | Query the NVD for CVSS data. |
| `ghsa` | boolean | `true` | free |  | Query GitHub advisories. |
| `kev` | boolean | `true` | free |  | Query the CISA KEV catalogue. |
| `epss` | boolean | `true` | free |  | Query FIRST EPSS scores. |

### `security.severity_mapping`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `kev_is_blocker` | boolean | `true` | tighten_only, tighten true |  | A KEV-listed vulnerability is a blocker. |
| `epss_major` | number | `0.1` | tighten_only, tighten le | &gt;= 0, &lt;= 1 | EPSS score at or above which a finding is major. |
| `cvss_blocker` | number | `9.0` | tighten_only, tighten le | &gt;= 0, &lt;= 10 | CVSS score at or above which a finding is a blocker. |
| `cvss_major` | number | `7.0` | tighten_only, tighten le | &gt;= 0, &lt;= 10 | CVSS score at or above which a finding is major. |

### `security.accepted_risks[]`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `id` | string | required | free | min length 1, max length 128 | Advisory or rule id being accepted. |
| `reason` | string | required | free | min length 1 | Why the risk is accepted. Required. |
| `expires` | date (YYYY-MM-DD) | required | free |  | Date after which the acceptance is ignored with a warning. |

### `security.local_scanners`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `gitleaks` | boolean | `false` | free |  | Run gitleaks in the sandbox. |
| `semgrep` | boolean | `false` | free |  | Run semgrep in the sandbox. |
| `trivy` | boolean | `false` | free |  | Run trivy fs in the sandbox. |

## `ops`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `allowed_namespaces` | list of string | `[]` | org_only |  | Kubernetes namespaces darryl may read. Org-only. |
| `prometheus_url` | string or null | `null` | org_only |  | Prometheus endpoint. Org-only (egress). |
| `loki_url` | string or null | `null` | org_only |  | Loki endpoint. Org-only (egress). |
| `argocd_url` | string or null | `null` | org_only |  | Argo CD endpoint. Org-only (egress). |
| `redaction_patterns` | list of string | `[]` | free, mergeable set (union) |  | Regular expressions redacted from tool output. Lower layers may only add. |
| `max_log_lines` | integer | `500` | free | &gt;= 1, &lt;= 10000 | Maximum log lines returned per query. |
| `max_query_points` | integer | `11000` | free | &gt;= 1 | Maximum points per metrics range query. |
| `incident_window_minutes` | integer | `120` | free | &gt;= 1 | Window around an alert used to correlate changes. |

## `implementer`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `branch_template` | string | `"pam/{task_key}-{slug}"` | free | min length 1, max length 200 | Branch name template; {task_key} and {slug} are filled in. |
| `commit_template` | string | `"feat: {summary}"` | free | max length 200 | Commit message template; {summary} is filled in. |
| `mr_title_template` | string | `"{task_key}: {summary}"` | free | max length 200 | Change request title template. |
| `mr_body_template` | string | `"## What\n{summary}\n\n## Why\n{why}\n\n## How tested\n{tests}\n\n## Risks\n{risks}\n"` | free | max length 8000 | Change request body template with what, why, how tested and risks sections. |
| `labels` | list of string | `["ai-generated"]` | free |  | Labels added to every change request. |
| `reviewers` | list of string | `[]` | free |  | Reviewers requested on every change request. |
| `assignees` | list of string | `[]` | free |  | Assignees set on every change request. |
| `mr_draft` | boolean | `false` | free |  | Open change requests as drafts. |
| `check_commands` | list of string or null | `null` | free | max length 20 | Commands run in the sandbox to verify the change. Null means detect them from the repository. |
| `sandbox` | section, see `implementer.sandbox` | nested defaults | free |  | Sandbox settings. |
| `git_identity` | section, see `implementer.git_identity` | nested defaults | free |  | Git author for implementer commits. |
| `protected_paths` | list of string | `[".gitlab-ci.yml", ".github/**", "**/package-lock.json", "**/pnpm-lock.yaml", "**/yarn.lock"]` | free, mergeable set (union) |  | Paths the implementer must not touch. Lower layers may only add. |
| `extra_executables` | list of string | `[]` | org_only |  | Executables added to the sandbox allow-list. Org-only. |

### `implementer.sandbox`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `image` | string | `"code-squad-sandbox-node:latest"` | org_only | min length 1, max length 256 | Sandbox container image. Org-only. |
| `cpu` | string | `"1"` | free | max length 16 | CPU limit for the sandbox. |
| `memory` | string | `"2Gi"` | free | max length 16 | Memory limit for the sandbox. |
| `timeout_seconds` | integer | `1800` | tighten_only, capped by limits.max_wall_clock_seconds | &gt;= 1 | Wall-clock limit for one implementation run. Cannot exceed limits.max_wall_clock_seconds. |

### `implementer.git_identity`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `name` | string | `"pam (code-squad)"` | free | min length 1, max length 128 | Commit author name. |
| `email` | string | `"pam@code-squad.invalid"` | free | min length 3, max length 254 | Commit author email. |

## `llm`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `base_url` | string or null | `null` | org_only |  | LiteLLM gateway URL. Org-only (egress). |
| `api_key_secret` | string or null | `"llm-api-key"` | free, secret name | pattern ^[a-z0-9][a-z0-9._-]{0,252}$ | Secret name holding the gateway key. |
| `tag_template` | list of string | `["squad:code-squad", "project:{project}", "agent:{agent}"]` | free |  | LiteLLM tags sent with each call. {project} and {agent} are filled in. |
| `budget_usd_per_day` | number or null | `null` | tighten_only, tighten le | &gt;= 0 | Daily spend cap per project. Lower layers may only lower it. |
| `aliases` | map of string to string | `{}` | free |  | Model alias to gateway model name. |

## `observability`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `otlp_endpoint` | string or null | `null` | org_only |  | OTLP collector endpoint. Org-only (egress). |
| `sampling_ratio` | number | `1.0` | free | &gt;= 0, &lt;= 1 | Trace sampling ratio between 0 and 1. |
| `content_capture` | one of `FULL`, `METADATA` | `"METADATA"` | org_only |  | Whether prompts and diffs may appear in traces. Org-only. |
| `log_level` | one of `DEBUG`, `INFO`, `WARNING`, `ERROR` | `"INFO"` | free |  | Log level. |

## `limits`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `max_tokens` | integer | `200000` | org_only | &gt;= 1 | Platform ceiling for tokens per invocation. |
| `max_iterations` | integer | `50` | org_only | &gt;= 1 | Platform ceiling for model turns. |
| `max_wall_clock_seconds` | integer | `1800` | org_only | &gt;= 1 | Platform ceiling for wall-clock seconds. |
| `max_tool_calls` | integer | `200` | org_only | &gt;= 1 | Platform ceiling for tool calls. |
| `max_skills` | integer | `50` | org_only | &gt;= 1 | Platform ceiling for skills per run. |
| `max_skill_bytes` | integer | `65536` | org_only | &gt;= 1 | Platform ceiling for bytes per skill. |
| `max_total_skill_bytes` | integer | `262144` | org_only | &gt;= 1 | Platform ceiling for total skill bytes. |
| `max_prompt_extra_chars` | integer | `4000` | org_only | &gt;= 1 | Platform ceiling for prompt_extra length. |

## `secrets`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `provider` | one of `k8s_files`, `env`, `file`, `vault` | `"k8s_files"` | org_only |  | Where secret values come from. Org-only. |
| `allowed_patterns` | list of string | `["^[a-z0-9][a-z0-9._-]*$"]` | org_only |  | Regular expressions a secret name must fully match. Org-only. |

## `posting`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `force_dry_run` | boolean | `false` | org_only |  | When true, no lower layer can enable external writes. Org-only. |

## `repo_config`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `allow_head_ref` | boolean | `false` | org_only |  | Allow a request to read .squad/config.yml from the change request head. Org-only; off by default. |

### `extra_agents[]`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `id` | string | required | free | pattern ^[a-z][a-z0-9]{1,30}$ | Agent id: a lowercase single token, not a built-in id. |
| `description` | string | required | free | min length 1, max length 200 | One-line role description. |
| `prompt_path` | string | required | free | min length 1, max length 512 | Path to the agent prompt markdown file. |
| `knowledge_dirs` | list of string | `[]` | free |  | Knowledge directories readable through read_knowledge. |
| `tool_preset` | one of `review_readonly`, `review_publish` | `"review_readonly"` | free |  | Tool set: review_readonly, or review_publish which adds publish_review. |
| `model` | string or null | `null` | free | pattern ^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$ | Model alias. Defaults to the platform default. |
| `routes` | list of string | `[]` | free |  | Changed-file globs that route to this agent. |

## Repository file extra key

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `extends` | string or null | `null` | free | min length 1, max length 64 | Profile to apply before this file's own keys (built-in or registry profile). |

## Project registry entries

### `projects.yaml`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `profiles` | map of sections, see `Organisation and repository keys` | nested defaults | free |  | Named profiles: reusable bundles of overrides. |
| `projects` | list of sections, see `projects.yaml.projects[]` | nested defaults | free |  | Project registry entries, least to most specific by match. |

### `projects.yaml.projects[]`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `match` | string | required | free | min length 1, max length 256 | Project key or glob. '*' stays within one path segment, '**' crosses them. |
| `key` | string or null | `null` | free | min length 1, max length 256 | Canonical project label used in tags and logs. Defaults to the request key. |
| `provider` | one of `gitlab`, `github`, `auto` or null | `null` | free |  | VCS provider for this project. |
| `base_url` | string or null | `null` | free |  | API base URL for this project's host. |
| `auth` | section, see `projects.yaml.projects[].auth` | nested defaults | free |  | Credential secret names. |
| `extends` | string or null | `null` | free | min length 1, max length 64 | Profile applied before this entry's own overrides. |
| `overrides` | section, see `Organisation and repository keys` | nested defaults | free |  | Configuration overrides for matching projects. |

### `projects.yaml.projects[].auth`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `token_secret` | string or null | `null` | free, secret name | pattern ^[a-z0-9][a-z0-9._-]{0,252}$ | Secret name holding the VCS access token. |
| `app_id` | integer or null | `null` | free | &gt;= 1 | GitHub App id (numeric). |
| `installation_id` | integer or null | `null` | free | &gt;= 1 | GitHub App installation id (numeric). |
| `private_key_secret` | string or null | `null` | free, secret name | pattern ^[a-z0-9][a-z0-9._-]{0,252}$ | Secret name holding the GitHub App private key (PEM). |

## Accepted findings file

### `baseline.yml`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `accepted` | list of sections, see `baseline.yml.accepted[]` | nested defaults | free |  | Accepted findings with mandatory expiry dates. |

### `baseline.yml.accepted[]`

| Key | Type | Default | Merge policy | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `finding_id` | string or null | `null` | free | min length 1, max length 128 | Stable finding id to accept. Use rule_id and file when the id changes. |
| `rule_id` | string or null | `null` | free | min length 1, max length 128 | Rule id to accept within the file. |
| `file` | string | required | free | min length 1 | File the accepted finding belongs to. |
| `reason` | string | required | free | min length 1 | Why the finding is accepted. Required. |
| `expires` | date (YYYY-MM-DD) | required | free |  | Mandatory expiry date; expired entries are ignored. |
