# FAQ

### Does the squad ever merge a change?

No. No agent has a merge capability, and no tool approves a change request unless `vcs.approve_mode` allows a formal approval
(default `none`). Humans merge.

### Can the squad change my cluster?

No. `darryl` is read-only by construction, and its RBAC grants read verbs only, without secrets. `pam` can create and delete pods
in its own sandbox namespace only. See [RBAC](deployment/rbac.md).

### What happens if a reviewer fails?

Michael's verdict becomes `incomplete`, the commit status is `pending` (never `success`), and the summary names the failed reviewer
and the reason. A review that finishes without its data is also `incomplete` or carries a warning. Nothing is reported as a clean pass
when it was not one.

### How do I run it without writing to the VCS?

Send `"post": false`, or set `posting.force_dry_run: true` in the organisation file to turn writes off for every project. In dry run the
agents do all the work, and the result lists the attempted writes in `warnings`.

### Does the squad read my repository configuration from the change request?

No, by default it reads `.squad/config.yml` and the skills from the target branch. Reading from the head is an organisation decision,
and it logs a warning when used. See [ADR 0004](decisions/0004-skills-from-base-branch.md).

### What if a repository file tries to loosen a setting?

The whole repository file is ignored, not partly applied. The reason is listed in the result's warnings and in
`squad config explain --repo-config`. See [Configuration concepts](configuration/concepts.md).

### Is `/invocations` authenticated?

Not by the application. Restrict it by network, and never route it through the ingress without an authenticating proxy or mTLS.
See [Ingress and webhooks](deployment/ingress-webhooks.md) and [Threat model](security/threat-model.md).

### Can I use GitHub and GitLab in the same deployment?

Yes. Each project's provider is set in the project registry, and both providers can be active at once. See the `multi-provider` values
example in [Helm](deployment/helm.md#example-values-files).

### Why are the agent names people's names?

The ids are character names from *The Office* (US), chosen in the brief for discoverability. Every document and output uses the functional
role. The mapping is in `_common/registry.py`.

### Which model does each agent use?

The default aliases are `haiku-5-5` for michael's optional intent classifier and `sonnet-5-5` for the other agents. Each alias is sent to the
LiteLLM gateway unchanged. A project can override the model per agent with `agents.<id>.model`. The generated
[agent defaults](reference/agents.md) page lists the built-in values.

### Why did the squad not find a bug I know about?

Common reasons: the defect is outside the changed lines; the file matches `review.ignore_globs`; a threshold hid the finding
(`review.min_confidence_to_publish`, `review.max_findings`); the reviewer for that stack did not run (check the routes and the
`agents` section in the result's `data`); or the model missed it. Replay the request in dry run and read the findings before the
publication limits. The [runbook](operations/runbook.md#replay-an-invocation-in-dry-run) explains the replay.

### Why did the squad flag a line that is not mine?

A finding is allowed on unchanged code only when the change breaks it, and it is then anchored to the changed line that causes the
break. A finding outside the changed hunks goes to the summary, not inline.

### The verdict says `request_changes` but the findings look minor. Why?

Minor and nit findings never request changes on their own. Check the other findings: a blocker always requests changes, and in the
high risk tier any major does too. Michael's `data.risk` field shows the tier and its reasons. A specialist's own withheld approval
(for example dwight in offline mode) also keeps its verdict. The thresholds are in `review.verdict`.

### Can I add a language?

Yes, without code: declare an extra agent in the organisation file, with its prompt, knowledge and routes. See
[Extra agents](agents/extra-agents.md). The chart does not yet deploy extra agents; that is an open item.

### What does pam need to implement a task?

A project registry entry with a token that has `write_repository` scope (GitLab) or contents write (GitHub App), the implementer
settings if the defaults do not fit, and a sandbox namespace. In a cluster the sandbox must be on: without `SANDBOX_NAMESPACE`, pam runs
repository commands in its own container. See [pam](agents/pam.md).

### Where are the logs and metrics?

Metrics are served on `/metrics` of each agent, and logs are JSON on stderr. The names and fields are in the
[runbook](operations/runbook.md).

### Can I use my own identity provider?

The squad does not have user accounts. Access control is the network, the webhook secrets, the commenter allow-list and the VCS token
scopes. Put an identity layer in front of any route you expose.

### Is there a hosted version?

No. The squad is a self-hosted platform, deployed with the Helm chart or Docker Compose.

### How do I report a security problem?

Use GitHub's private vulnerability reporting, as described in [SECURITY.md](https://github.com/acarmisc/the-office-ai-squad/blob/main/SECURITY.md). Do not open a public issue or change request for it.
