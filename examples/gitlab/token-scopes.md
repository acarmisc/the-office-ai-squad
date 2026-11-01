# GitLab token scopes

The squad talks to GitLab with one access token per project (or one group token that the
registry references). The token is stored as a secret and referenced by name, for example
`gitlab-payments-token`, in `projects.yaml` under `auth.token_secret`.

## Recommended token

Create a **project access token** (or a group access token) for a dedicated bot account.

| Setting | Value | Why |
| --- | --- | --- |
| Role | Developer | Enough to comment, set commit statuses and read pipelines. Use Maintainer only where pam must push to protected branches, which the squad never does. |
| Scopes | `api`, `read_repository` | `api` covers merge request reads and writes (diffs, discussions, notes, approvals), commit statuses, pipelines, job logs and issues. `read_repository` covers file reads through the repository API. |
| Scope added for pam | `write_repository` | Required only when `pam` runs in implementer mode, because it pushes a branch. Omit it for a review-only deployment. |
| Expiry | Set one (for example 180 days) | Rotate on expiry. See below. |

The bot user GitLab creates for a project access token has a login such as `project_<id>_bot`.
Set `vcs.bot_username` to that login in the organisation file or the project registry. The
squad ignores events and comments from this login to avoid reacting to itself.

## What each scope enables

| Operation | Endpoints (GitLab REST v4) | Scope |
| --- | --- | --- |
| Read the change request and its diffs | `merge_requests/:iid`, `merge_requests/:iid/diffs` | `api` |
| Post inline discussions and summary notes | `merge_requests/:iid/discussions`, `merge_requests/:iid/notes` | `api` |
| Set the commit status `ai-review/<agent>` | `statuses/:sha` | `api` |
| Submit an approval (only when `vcs.approve_mode` allows it) | `merge_requests/:iid/approve` | `api` |
| Read pipelines and job logs | `pipelines`, `pipelines/:id/jobs` | `api` |
| Read files and trees at a ref | `repository/files/:path/raw`, `repository/tree` | `read_repository` or `api` |
| Read the bot identity | `user` | `api` |
| Create a branch and open a merge request (pam) | `repository/branches`, `merge_requests` | `api` with `write_repository` for the push |

## Rotation

1. Create the new token with the same role and scopes.
2. Update the secret the registry names (for example `gitlab-payments-token`) in the secret
   store. The squad reads secret values through the secret provider on each run, so a rotated
   file is picked up without a restart.
3. Revoke the old token in GitLab.
4. Run a dry-run review on a test merge request and check the result for `warnings`.

## What not to do

- Do not use a personal access token of a developer. Reviews then appear as that person and
  the bot-loop protection cannot tell the squad's own comments from theirs.
- Do not put the token value in `projects.yaml`, in a CI variable of the consuming project, or
  in a values file. Only the secret name belongs in configuration.
- Do not grant `write_api` or Owner. The squad never merges and never changes project settings.
