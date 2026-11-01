<!-- generated — do not edit. Source: scripts/gen_docs.py. Regenerate with: just docs-gen -->

# VCS capability matrix

Generated from the capability sets of `GitLabProvider` and `GitHubProvider`
(`code_squad/_common/vcs/base.py`). GitHub authenticates either as a GitHub App
or with a personal access token, which changes the capability set.

| Capability | GitLab | GitHub (App) | GitHub (token) |
| --- | --- | --- | --- |
| `check_runs` | no | yes | no |
| `commit_status` | yes | yes | yes |
| `batched_review` | no | yes | yes |
| `approve` | yes | yes | yes |
| `draft_change_request` | yes | yes | yes |
| `resolve_thread` | yes | no | no |
| `ci_logs` | yes | yes | yes |
| `issues` | yes | yes | yes |
| `push` | yes | yes | yes |

## Fallbacks

| Capability | Fallback or effect |
| --- | --- |
| `check_runs` | Without a GitHub App, verdicts are published as commit statuses and michael adds the warning 'check runs unavailable; used commit status'. |
| `commit_status` | Verdicts use the commit status context ai-review/&lt;agent&gt;. Check runs are preferred on GitHub App authentication. |
| `batched_review` | GitLab has no batched review. Inline comments are posted as discussions. |
| `approve` | A formal approval is submitted only when vcs.approve_mode allows it. A provider that refuses it adds the warning 'formal review is not supported by this provider'. |
| `draft_change_request` | pam opens a draft only when implementer.mr_draft is true. |
| `resolve_thread` | Not used by the publication path. GitHub raises CapabilityError because resolving threads needs GraphQL, which is not implemented. |
| `ci_logs` | darryl trims job logs to the failure region before the model reads them. |
| `issues` | Issue reads and comments use the same provider. Jira is a separate, read-only tracker used for task text. |
| `push` | pam pushes over HTTPS with the provider credentials. Without this capability an implementation run cannot publish its branch. |
