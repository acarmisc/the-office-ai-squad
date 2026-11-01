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
`fallback_model` is used once, after a truncated answer or after a gateway throttle or server error
(HTTP 429 or 5xx). Other client errors do not trigger it. Model aliases must be in
`llm.allowed_models` when the organisation sets that list.

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

Goal: record a known advisory that the team will fix later. Accepted risks are organisation-only. Set them in
the organisation file, and keep them out of repository files and registry entries: a layer that sets them is
rejected as a whole and the review continues without it. Each entry needs a reason and an expiry date.

An accepted risk matches a finding whose rule id or reference names the risk id. `package` narrows the match to
findings whose text names that package, and `path` narrows it to changed files under that glob. A scoped risk
therefore does not hide a finding for another package. Each suppression is listed as a warning on the result.

<!-- validate: config:org -->
```yaml
security:
  accepted_risks:
    - id: GHSA-xxxx-xxxx-xxxx
      reason: Affected code path is not reachable; the service runs without untrusted input.
      expires: 2027-01-31
      package: lodash
      path: "services/web/**"
```

Expired entries are ignored with a warning in the published summary, so the review shows when a risk needs a
new decision.

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

## 9. Bound the spend of one run

Goal: cap how much one review can spend and how long it can run. The token ceiling is an organisation limit
on a whole run, across all of its turns. Per-agent budgets can only lower the platform values, and a run that
reaches one of them returns `incomplete` with a warning.

<!-- validate: config:org -->
```yaml
limits:
  max_run_tokens: 200000
agents:
  dwight:
    budgets:
      wall_clock_seconds: 600
      tool_calls: 60
```

The squad does not convert tokens to money. For a daily spend cap per project, set a budget at the LiteLLM
gateway and key it on the `project:<project>` tag that every call carries.

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
