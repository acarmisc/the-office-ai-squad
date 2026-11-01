# Configuration recipes

Each recipe is a complete, valid overlay for the file it names. The YAML blocks are validated by the
test suite: a repository block must validate as a repository file and must not loosen a restricted
setting; a registry block must validate as a project registry. Recipes that need an organisation-level
change are marked as such.

The concepts behind them are in [Configuration concepts](concepts.md). For a repository file to take
effect, it must be on the target branch of the project, and it must be valid. An invalid repository
file is ignored as a whole.

## 1. Strict profile for payments code

Goal: payments code gets the strict profile, and a repository cannot loosen it. Set the profile in the
registry (organisation level), then let the repository add its own sensitive paths.

Registry entry (`projects.yaml`, platform team):

<!-- validate: projects -->
```yaml
projects:
  - match: platform/payments-api
    provider: gitlab
    base_url: https://gitlab.example.com
    auth:
      token_secret: gitlab-payments-token
    extends: strict
    overrides:
      trigger:
        on_push: true
```

Repository file (`.squad/config.yml`, project team). Adds paths that raise the risk tier. A list of
sensitive paths is mergeable, so the repository adds to the platform list and cannot remove entries:

<!-- validate: config -->
```yaml
routing:
  sensitive_paths:
    - "src/ledger/**"
    - "src/refunds/**"
review:
  min_severity_inline: nit
```

Result: the strict thresholds apply, a blocker still requests changes, and approvals stay off
(`vcs.approve_mode` is `none` in the strict profile).

## 2. Lenient profile for prototypes

Goal: experiments are reviewed without noise. Use the built-in `lenient` profile in the registry.
Lenient raises the bar for what is published, so most findings stay in the summary.

<!-- validate: projects -->
```yaml
projects:
  - match: acme/prototype-*
    extends: lenient
    overrides:
      review:
        max_findings: 10
```

Keep the lenient profile away from production repositories: it lowers the bar for what is published by
design.

## 3. Swap the model for one agent

Goal: run `jim` on a different model and temperature for one repository. Model and temperature are
free settings, so a repository may set them. Platform limits still apply to tokens and iterations.

<!-- validate: config -->
```yaml
agents:
  jim:
    model: sonnet-5-5
    fallback_model: haiku-5-5
    temperature: 0.1
```

The model alias is sent to the LiteLLM gateway unchanged. Use an alias that the gateway serves. The
`fallback_model` is used once, after a truncated answer; it is not used when the gateway is overloaded.

## 4. Disable one agent for a repository

Goal: a repository with no Java code does not run `angela`. Disabling a reviewer is allowed for every
agent except those in `routing.always_run` (by default only `dwight`, which cannot be disabled by a lower
layer).

<!-- validate: config -->
```yaml
agents:
  angela:
    enabled: false
```

A disabled agent returns `incomplete` with the reason "disabled by configuration" if it is called
directly. Under `michael` it is removed from the plan and does not affect the verdict.

## 5. Add a routing rule

Goal: a React hooks directory also goes to `jim`. Routes are a mergeable list: the repository adds
entries to the built-in routes and cannot remove them.

<!-- validate: config -->
```yaml
routing:
  routes:
    - glob: "src/hooks/**"
      agents: [jim]
      requires: [react]
```

The `requires` field applies the route only when the stack is present in the change or in the manifests.
Remove `requires` to route regardless of the stack.

## 6. Ignore generated code

Goal: generated files are not reviewed, and findings on them are not published. Ignore globs are a
mergeable list.

<!-- validate: config -->
```yaml
review:
  ignore_globs:
    - "src/generated/**"
    - "**/*.stories.tsx"
```

A finding on an ignored file is demoted to a general note with the reason "file matches
review.ignore_globs". It still counts towards the verdict, so an ignored file cannot hide a blocker from
the verdict.

## 7. Accepted findings

Goal: record a known finding that the team will fix later. The file is `.squad/baseline.yml`. Each
entry needs a reason and an expiry date, which the schema enforces.

<!-- validate: baseline -->
```yaml
accepted:
  - rule_id: REACT-HOOKS-004
    file: src/legacy/Table.tsx
    reason: Legacy table is replaced next quarter; tracked in WEB-412.
    expires: 2027-03-31
```

> **Not applied yet.** The baseline file is validated and documented, but the review does not read it
> at run time in this version. The accepted-risk setting below is applied and is the working option for
> dependency advisories.

For advisories that dwight reports, use `security.accepted_risks`. An entry suppresses matching findings
until its expiry date, and each suppression is listed as a warning on the result:

<!-- validate: config -->
```yaml
security:
  accepted_risks:
    - id: GHSA-xxxx-xxxx-xxxx
      reason: Affected code path is not reachable; the service runs without untrusted input.
      expires: 2027-01-31
```

Accepted risks from a repository are a known open point for review (see [ADR 0009](../decisions/0009-dwight-offline-mode.md)).
An organisation that wants to restrict them to the organisation layer can change the field's policy in the
schema.

## 8. Add a language with an extra agent

Goal: add a Python reviewer without code. This is an organisation-level change, because extra agents are
organisation-only.

<!-- validate: config:org -->
```yaml
extra_agents:
  - id: oscar
    description: Python reviewer for correctness, typing and security hygiene.
    prompt_path: /etc/squad/agents/oscar/prompt.md
    knowledge_dirs:
      - /etc/squad/agents/oscar/knowledge
    tool_preset: review_publish
    model: sonnet-5-5
    routes:
      - "**/*.py"
```

The agent needs its own Deployment and the prompt on disk. See [Extra agents](../agents/extra-agents.md)
for the steps and the current chart limitation.

## 9. Per-project LLM budget

Goal: cap the model spend of one project. Budget is set per project in the registry.

<!-- validate: projects -->
```yaml
projects:
  - match: acme/web-app
    extends: balanced
    overrides:
      llm:
        budget_usd_per_day: 50
```

> **Declared, not enforced.** `llm.budget_usd_per_day` is validated and merged, but the squad does not
> stop calls when the budget is reached in this version. Enforce the budget at the gateway, keyed on the
> `project:<project>` tag that every call carries, until the squad enforces it.

## 10. Run reviews for a project on every push

Goal: review each new push to an open change request, not only the first assignment. Pushes are off by
default because they multiply the cost of reviews.

<!-- validate: config -->
```yaml
trigger:
  on_push: true
  debounce_seconds: 120
```

The debounce window collapses a burst of pushes for the same head commit into one run. A push to a draft
change request is still skipped while `trigger.skip_draft` is true.

## Checking a recipe

Validate the file locally, and look at the effective result before you push:

```bash
uv run squad config validate .squad/config.yml
uv run squad config explain acme/web-app --repo-config .squad/config.yml
```

`explain` lists every key with the layer that set it, and it prints the rejected layers if the file
breaks a rule.
