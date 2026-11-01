<!-- generated — do not edit. Source: scripts/gen_docs.py. Regenerate with: just docs-gen -->

# Tool policy

Generated from `code_squad/_common/tool_policy.py` and the `tools` of every built-in
agent specification. Extra agents declared in configuration use the presets
`review_readonly` and `review_publish` and are not listed here.

Classes: `read` tools change nothing; `local_mutation` tools change only the
sandbox working copy; `external_write` tools change a remote system and are refused
when posting is disabled (dry-run).

| Tool | Class | Agents |
| --- | --- | --- |
| `apply_patch` | local_mutation | `pam` |
| `ci_job_log` | read | `darryl` |
| `ci_runs` | read | `darryl` |
| `commit` | local_mutation | `pam` |
| `deployment_status` | read | `darryl` |
| `finish` | read | `angela`, `darryl`, `dwight`, `jim`, `michael`, `pam` |
| `get_project_skills` | read | `angela`, `darryl`, `dwight`, `jim`, `pam` |
| `get_review_context` | read | `angela`, `darryl`, `dwight`, `jim` |
| `get_task` | read | `pam` |
| `k8s_describe` | read | `darryl` |
| `k8s_events` | read | `darryl` |
| `k8s_get` | read | `darryl` |
| `k8s_logs` | read | `darryl` |
| `k8s_top` | read | `darryl` |
| `list_tree` | read | `angela`, `darryl`, `dwight`, `jim`, `pam` |
| `load_skill` | read | `angela`, `darryl`, `dwight`, `jim`, `pam` |
| `logs_query` | read | `darryl` |
| `lookup_cve` | read | `dwight` |
| `lookup_vulnerabilities` | read | `dwight` |
| `open_change_request` | external_write | `pam` |
| `parse_dependencies` | read | `dwight` |
| `prom_query` | read | `darryl` |
| `publish_review` | external_write | `angela`, `darryl`, `dwight`, `jim` |
| `push_branch` | external_write | `pam` |
| `read_file` | read | `angela`, `darryl`, `dwight`, `jim`, `pam` |
| `read_knowledge` | read | `angela`, `darryl`, `dwight`, `jim`, `michael`, `pam` |
| `recent_changes` | read | `darryl` |
| `rollout_history` | read | `darryl` |
| `run_checks` | local_mutation | `pam` |
| `run_command` | local_mutation | `pam` |
| `sandbox_diff` | read | `pam` |
| `sandbox_list` | read | `pam` |
| `sandbox_read` | read | `pam` |
| `search_advisories` | read | `dwight` |
| `search_repo` | read | `angela`, `darryl`, `dwight`, `jim`, `pam` |
| `start_work` | local_mutation | `pam` |
| `write_file` | local_mutation | `pam` |

## Classified but not exposed by a built-in agent

None.

## External write tools

`open_change_request`, `publish_review`, `push_branch`.
