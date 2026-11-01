# GitHub Enterprise Server notes

The squad supports GitHub Enterprise Server (GHES) through the same GitHub provider as
github.com. Only the API base URL and the advisory sources differ.

## Configuration

Set the API base URL for the host, with the `/api/v3` path that GHES uses. Put it in the project
registry entry, so that only that project uses the host:

```yaml
projects:
  - match: platform/legacy-api
    provider: github
    base_url: https://ghes.example.com/api/v3
    auth:
      app_id: 12345
      installation_id: 67890
      private_key_secret: ghes-app-key
    extends: balanced
```

`provider: github` must be explicit. The `auto` provider only infers GitHub from the hosts
`github.com` and `api.github.com`; for any other host it refuses and asks for an explicit
provider.

The clone host for pam is taken from the API base URL (`https://<host>/<owner>/<repo>.git`),
so the GHES host must serve git over HTTPS on that name.

## Things that differ from github.com

| Area | Note |
| --- | --- |
| Webhooks | Same route, `/webhooks/github`, same `X-Hub-Signature-256` check. Configure the webhook on the GHES organisation or repository with the same secret. |
| Advisory data | dwight queries GitHub advisories at `api.github.com` (the `ghsa` source), which is a public host. A GHES deployment without internet egress must switch `security.sources.ghsa` off or allow that host through the egress proxy. Otherwise the run is marked unverified, as for any unreachable source. |
| Private CA | When GHES or the proxy uses a private certificate authority, the image must trust it. The platform has no setting for an extra CA bundle. TODO(architect): confirm whether the image should trust a mounted CA file. |
| Rate limits | GHES honours the same primary and secondary limit headers. The client waits as the headers request. |
| Check runs | Available with GitHub App authentication on GHES versions that support the Checks API. Otherwise verdicts use commit statuses, with the warning recorded on the result. |

## Permissions for a GitHub App

These are the permissions in `github-app-manifest.json`. Use the minimum that matches the agents
you deploy.

| Permission | Level | Used for | Needed when |
| --- | --- | --- | --- |
| Metadata | read | Repository and installation identity (required by GitHub) | always |
| Contents | read | Reading files, trees and the base branch | always |
| Contents | write | Creating branches and pushing the implementer's branch | only when `pam` is deployed and used; lower it to read otherwise |
| Pull requests | write | Reviews, inline comments, creating pull requests | always |
| Issues | write | Summary comments on issues and pull requests, comments on incidents | always |
| Checks | write | Check runs for verdicts (App authentication only) | recommended |
| Commit statuses | write | Commit statuses `ai-review/<agent>` | always |
| Actions | read | Workflow runs and job logs for darryl | when darryl reads CI |

The manifest's `default_events` are `pull_request`, `issue_comment`,
`pull_request_review_comment` and `issues`. Subscribe to `issues` only when `pam` picks up
issues assigned to the bot.

## Checking the installation

Install the App on the repositories that the squad should review, then run a dry-run review
(`post: false`) on one pull request. The result lists `warnings` for any capability that fell
back, and the `config_hash` in `stats` identifies the configuration that produced it.
