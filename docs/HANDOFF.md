# Handoff

This page is for the next person who picks up the project. It says what exists, how to run it, what was verified, what is known to be
incomplete or wrong, and what to do next. Each limitation names the place where it is described. Items marked `TODO(architect)` need a
decision from the solution architect before the platform goes to production.

## What exists

- **Platform.** One Python package, `code_squad`, with six built-in agents served from one container image: `michael`, `jim`, `angela`,
  `dwight`, `darryl` and `pam`. The platform code is in `src/code_squad/_common/`.
- **Contract.** HTTP endpoints `/ping`, `/ready`, `/metrics`, `/invocations` and `/jobs/{id}`. `/invocations` and `/jobs/{id}` take an
  optional shared bearer token. Webhook receivers on `michael` for GitLab and GitHub, enabled per provider. See
  [HTTP contract](architecture/contract.md) and [Hardening](security/hardening.md#api-authentication).
- **Configuration.** Five layers with tighten-only and org-only rules, a schema that generates the reference, validation and explain commands.
  See [Configuration concepts](configuration/concepts.md) and [recipes](configuration/recipes.md).
- **VCS.** GitLab and GitHub providers behind one protocol, with a conformance suite. See the [GitLab](vcs/gitlab.md) and [GitHub](vcs/github.md) pages.
- **Deployment.** A multi-purpose container image, a Helm chart with network policies, RBAC, a webhook-only ingress and seven example values files,
  Docker Compose with an offline fake LLM, kind scripts and an HTTP smoke test.
- **Documentation.** This site, built with `mkdocs --strict`, with generated reference pages, validated examples and twelve decision records.
- **Examples and catalogue.** `examples/` (organisation, repository, GitLab and GitHub), `catalog-info.yaml` for Backstage.
- **Evaluation.** An offline replay harness with four golden cases for the reviewers, and scorers for recall, precision, false blockers and injection
  resistance.

## How to run

- **Offline, all six agents, about 10 minutes:** `docker compose -f deploy/compose.yaml up -d --build` then `scripts/smoke_test.sh compose`. See
  [Local environments](deployment/local.md).
- **One agent without containers:** `uv sync`, start `python -m deploy.fake_llm` on port 4000, then `just run-local michael` and `just invoke michael "smoke test"`.
- **Gate:** `just check`. The steps and what each one covers are in [Testing](testing/index.md).
- **Replay evaluation:** `just eval`. Live evaluation needs `EVAL_LIVE=1` and `LLM_BASE_URL`, and it is not part of the gate.
- **Production:** follow the [new project checklist](onboarding/new-project.md) for each project, and the [hardening checklist](security/hardening.md) for the
  platform. Read the known limitations below before enabling webhooks or pam.

## Validation performed

The validation below was run in the build environment for this milestone. Results are recorded as they were observed.

- Full gate, run at the end of this milestone, all green: `ruff check .`, `ruff format --check .` (395 files), `mypy src tests scripts eval deploy`
  (259 files), the full pytest suite, `gen_docs.py --check`, `gen_schemas.py --check`, `mkdocs build --strict`, the secret scan, the prompt checks, and
  `helm lint` with `kubeconform` for the default and example values.
- Hardening pass (after the milestone above): `just check` passed with 1617 tests, up from 1577. New coverage: the API token on
  `/invocations` and `/jobs/{id}` (401 without or with a wrong token, 200 with it, open endpoints stay open, specialists receive the
  header), the `squad_vcs_errors_total` counter on final failures (a respx 500 counts once after its retries, 404 does not count), the
  rendered chart environment for `WEBHOOK_PROVIDERS` and `SQUAD_API_TOKEN` (helm is required; the test skips without it), and the
  no-merge invariant on the protocol and the providers.
- One existing test was narrowed: `tests/config/test_cli.py` validated everything under `examples/` as squad configuration, which the CI workflow
  files no longer satisfy. It now validates `examples/org` and `examples/repo`; the CI files are validated by `tests/test_docs_examples.py`.
- Documentation tests: every block marked `<!-- validate: ... -->` validates against the platform models or the chart schema, including the
  recipes, the contract example, the helm overlays and the organisation example. The GitLab snippet, the GitHub workflow and the GitHub App
  manifest are parsed, and the manifest's permissions and events are checked against the documented set.
- Generated reference pages match the code (no drift).
- Catalogue: one System, one Component and one API per built-in agent, and the webhook paths exist only on `michael`.
- Real outputs captured from the committed code for the pages: the `jim` and `angela` results come from the eval replays; a consolidated `michael`
  result comes from the orchestrator run with the test fixtures. The `darryl`, `dwight` and `pam` samples are smoke-stub outputs and are labelled as
  showing shape only.
- Deployment artifacts (from the packaging milestone, see [Local validation](deployment/local-validation.md)): the compose demo passed; the kind demo
  failed at cluster creation in the validation environment; the Helm chart rendered and linted in the fallback check.

Validated: the multi-arch build (`linux/amd64` and `linux/arm64`, arm64 through emulation; see the validation record).

Not validated: the kind smoke test end to end; running the arm64 image; live model evaluation; the Kubernetes sandbox against a real cluster; the NetworkPolicy
allow-lists on an enforcing CNI; the GitLab and GitHub providers against live hosts (the recorded responses are the only evidence).

## Known limitations

These are the limitations that matter, grouped by risk. Each one is stated where it applies in the documentation.

### Security and operations

1. **`/invocations` is open unless a token is configured.** Without `SQUAD_API_TOKEN` or `SQUAD_API_TOKEN_FILE` the endpoints take no
   credential, and network controls are the only protection. The token is one shared secret with no caller identity, and it is read at
   start-up. See [API authentication](security/hardening.md#api-authentication) and [Threat model](security/threat-model.md).
2. **The sandbox falls back to a local process.** With `SANDBOX_NAMESPACE` unset, pam runs repository commands in its own container. The kind example
   turns the sandbox off, so the demo does this. See [pam](agents/pam.md).
3. **Job state is per replica.** The job store and webhook de-duplication are in memory, so michael should run as a single replica. The
   image includes the `redis` extra, so `SESSION_STORE_URL` is accepted, but de-duplication and the debounce still live in memory. See
   [Scaling and upgrades](deployment/scaling-upgrades.md).
4. **The whole Secret is mounted into every agent pod.** A compromised agent can read every key. See [Secrets](deployment/secrets.md#what-each-pod-can-read).
5. **Config maps are readable by darryl.** Their values reach the model after redaction. See [RBAC](deployment/rbac.md).
6. **Sandbox pod TTL is not applied.** A crashed run can leave a pod until its deadline. See [pam sequence](architecture/pam-sequence.md).
7. **Repository layers can accept advisories.** `security.accepted_risks` may be added by a repository file. See [recipe 7](configuration/recipes.md#7-accepted-findings).
8. **Secret providers `file` and `vault` do not work.** `file` is refused by the factory, and `vault` is a stub. See [Secrets](deployment/secrets.md#providers).

### Features declared but not applied

These keys are accepted by the schema, appear in the reference, and have no effect at run time. Do not rely on them until the gap is closed.

- Budgets: `agents.<id>.budgets.*` (tokens, wall clock, tool calls, cost hint), and `limits.max_tool_calls`.
- `agents.<id>.disabled_rules`, `severity_overrides`, `language`.
- `agents.<id>.fallback_model` applies after truncation only, not after an overload.
- Review: `summary_template`, `chunking`, `max_diff_bytes`, `suppressions_enabled` (in-code `squad-ignore` comments are not implemented), `baseline_file` (baseline files are validated but not read), `verdict.request_changes_on_blocker` (always on).
- Trigger: `slash_commands` (the list is fixed).
- VCS: `status_mode` (the context template is used; the mode is not).
- LLM: `llm.tag_template`, `llm.aliases`, `llm.budget_usd_per_day`, and the `llm.*` keys generally. The gateway URL and key come from the environment (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_API_KEY_FILE`); `llm.api_key_secret` does not select the key.
- Observability: `sampling_ratio`, `content_capture` (no effect), `log_level` (use `LOG_LEVEL`), `otlp_endpoint` (use `OTEL_EXPORTER_OTLP_ENDPOINT`).
- Operations: `ops.incident_window_minutes`.
- Sandbox: `implementer.sandbox.image`, `cpu` and `memory` (the chart's environment variables are used).
- Security: `security.local_scanners` (gitleaks, semgrep and trivy are not wired).
- Skills: the `builtin` source has no loader caller, so no built-in skills are loaded.
- Attachments: validated by the contract but not sent to the model.
- `cost_hint` in results is always `null`.
- Tool budgets: no tool-call or wall-clock budget is enforced per agent; the only enforced limits are the turn limit, the output token cap, the sandbox command and wall-clock budgets, and the per-request timeouts.

### Deployment and documentation drift

- The air-gapped example relies on `EGRESS_PROXY_URL`, which the model client does not read. Model traffic needs `HTTPS_PROXY` settings.
- No extra CA bundle setting exists for private certificate authorities. TODO(architect): decide whether to add one.
- Extra agents cannot be deployed by the chart. TODO(architect): decide whether the chart should render them.
- The CLI differs from the brief: there is `squad invoke`, `squad review` and `squad config schema|validate|explain|init`, not `squad <agent> review <target>`.
- Finding `category` is a free string in the model, not the enumeration the brief lists. Prompts use the brief's values.
- The result `stats` carry `input_tokens` and `output_tokens`, not a single `tokens` field.
- The `config.org` and `config.projects` blocks embedded in every values file are validated against the schema by
  `tests/test_values_examples_config.py`.
- By design, `/ready` reports only that the agent specification loaded. It does not call the model gateway, so a gateway outage does not
  make a pod unready. See [HTTP contract](architecture/contract.md).

### Evaluation and testing

- The evaluation set has four golden cases, all for `jim` and `angela`. No case covers `dwight`, `darryl` (including the three troubleshooting scenarios in the brief) or `pam` (the feature-with-change-request scenario).
- No live model evaluation has been run. Replay results measure the pipeline only.
- The kind smoke test has not run end to end; see the packaging validation record.
- The arm64 image has been built (emulated) but not run.

## Next steps

1. Fix the sandbox: make it fail closed when `SANDBOX_NAMESPACE` is unset (or refuse pam when `sandbox.enabled` is false outside an explicit
   test profile).
2. Decide whether the shared token is enough for `/invocations`, or whether it needs per-caller identity or mTLS, and record it in an ADR.
3. Split the Secret by agent and move the webhook secrets to their own Secret by default.
4. Apply or remove each declared-but-unapplied key in the list above, and make the reference show which keys are enforced.
5. Add the missing eval cases for `dwight`, `darryl` and `pam`, and run a live evaluation with a recorded model alias and date.
6. Run the kind smoke test and the arm64 image on a host that can create a cluster, and record the results in the validation page.
7. Decide the open points listed in the [decisions index](decisions/index.md#open-points-raised-in-the-adrs).
8. Replace the in-memory job store and de-duplication with a shared store, then allow more than one replica of michael.

## Open decisions

For the architect (TODO(architect)):

- Whether the shared bearer token on `/invocations` is the final model, or whether per-caller identity or mTLS is required (the token is
  implemented; the choice of layer is open).
- Whether pam is allowed to run on the local backend in a cluster at all, or only with the sandbox namespace present.
- Whether the chart should deploy extra agents, and how their prompts and knowledge are mounted.
- Whether the image should trust a mounted private CA bundle.
- Whether `review.ignore_globs` and `security.accepted_risks` should be organisation-only (ADR 0003 and ADR 0009).
- Whether the orchestrator should ever submit a formal approval (ADR 0010).
- Whether sandbox pods should become Jobs so that orphans are deleted (ADR 0005).
