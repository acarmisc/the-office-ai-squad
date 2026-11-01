# Handoff

This page is for the next person who picks up the project. It says what exists, how to run it, what was verified, what is known to be
incomplete or wrong, and what to do next. Each limitation names the place where it is described. Items marked `TODO(architect)` need a
decision from the solution architect before the platform goes to production.

The adversarial review and its fixes are recorded in [ADR 0013](decisions/0013-operational-readiness.md). The first real-project test is
in [First operational test](operations/first-operational-test.md).

## What exists

- **Platform.** One Python package, `code_squad`, with six built-in agents served from one container image: `michael`, `jim`, `angela`,
  `dwight`, `darryl` and `pam`. The platform code is in `src/code_squad/_common/`.
- **Contract.** HTTP endpoints `/ping`, `/ready`, `/metrics`, `/invocations` and `/jobs/{id}`. `/invocations` and `/jobs/{id}` require a
  bearer token and fail closed without one, unless `SQUAD_ALLOW_UNAUTHENTICATED=1` is set. Webhook receivers on `michael` for GitLab and
  GitHub, enabled per provider, with body limits applied before the signature check. See [HTTP contract](architecture/contract.md) and
  [Hardening](security/hardening.md#api-authentication).
- **Publication.** One pipeline, `findings.publish`, for every agent including `michael`. The verdict is computed over every schema-valid
  finding; a finding that cannot be anchored becomes a general note. Configuration notes appear in every summary. See
  [Review sequence](architecture/review-sequence.md).
- **Configuration.** Five layers with tighten-only and org-only rules, a schema that generates the reference, validation and explain commands.
  The last good organisation file is kept when a reload fails, and `posting.force_dry_run` is honoured even in a broken file. See
  [Configuration concepts](configuration/concepts.md) and [recipes](configuration/recipes.md).
- **VCS.** GitLab and GitHub providers behind one protocol, with a conformance suite. See the [GitLab](vcs/gitlab.md) and [GitHub](vcs/github.md)
  pages.
- **Deployment.** A multi-purpose container image, a Helm chart with network policies, RBAC, a webhook-only ingress and eight example values
  files (including `operational-test.yaml` for the first test), Docker Compose with an offline fake LLM, kind scripts and an HTTP smoke test.
- **Operations.** A runbook, the first operational test procedure, and `scripts/trial_review.sh`, which runs one dry-run or posting review and
  prints the verdict, findings, warnings, tokens and wall time.
- **Documentation.** This site, built with `mkdocs --strict`, with generated reference pages, validated examples and thirteen decision records.
- **Examples and catalogue.** `examples/` (organisation, repository, GitLab and GitHub), `catalog-info.yaml` for Backstage.
- **Evaluation.** An offline replay harness with four golden cases for the reviewers, and scorers for recall, precision, false blockers and
  injection resistance.

## How to run

- **Offline, all six agents, about 10 minutes:** `docker compose -f deploy/compose.yaml up -d --build` then `scripts/smoke_test.sh compose`. See
  [Local environments](deployment/local.md).
- **One agent without containers:** `uv sync`, start `python -m deploy.fake_llm` on port 4000, then
  `SQUAD_ALLOW_UNAUTHENTICATED=1 just run-local michael` and `just invoke michael "smoke test"`.
- **One real project:** follow [First operational test](operations/first-operational-test.md). It starts with dry runs through
  `scripts/trial_review.sh <michael-url> <project> <change-request> [--post]`.
- **Gate:** `just check`. The steps and what each one covers are in [Testing](testing/index.md).
- **Replay evaluation:** `just eval`. Live evaluation needs `EVAL_LIVE=1` and `LLM_BASE_URL`, and it is not part of the gate.
- **Production:** follow the [new project checklist](onboarding/new-project.md) for each project, and the [hardening checklist](security/hardening.md)
  for the platform. Use Redis for the session store before running more than one michael replica.

## Validation performed

Results are recorded as they were observed.

- **Gate, after ADR 0013.** `just check` passed: `ruff check` and `ruff format --check`, `mypy src tests scripts eval deploy` (267 files), the full
  pytest suite (1817 passed), `gen_schemas.py --check`, `gen_docs.py --check`, `mkdocs build --strict`, `helm lint` with `kubeconform` for the
  default and every example values file, the prompt checks and the secret scan (0 findings).
- **Compose smoke, after ADR 0013.** Built with the CA-trusting base image, all six agents passed `scripts/smoke_test.sh compose`. See
  [Local validation](deployment/local-validation.md#re-run-after-adr-0013-operational-readiness).
- **Tests added by ADR 0013.** Each fix has a test that fails on the previous code, in `tests/test_findings.py` (binary and truncated files, configuration
  notes), `tests/test_services.py` (kill switch in a broken file), `tests/test_server.py` (single-flight shares the session store, including an empty
  store), `tests/agents/test_dwight.py` (scoped accepted risk), `tests/michael/test_publish.py` (configuration notes through michael), and
  `tests/test_chart_render.py` (`allowUnauthenticated`). `tests/test_trial_report.py` covers the operational report helper.
- **Not validated:** the kind smoke test end to end; running the arm64 image; live model evaluation; the Kubernetes sandbox against a real cluster;
  the NetworkPolicy allow-lists on an enforcing CNI; the GitLab and GitHub providers against live hosts (the recorded responses are the only evidence);
  the first operational test itself, which has not been run.

## Known limitations

These are the limitations that matter, grouped by risk. Each one is stated where it applies in the documentation.

### Security and operations

1. **One shared API token.** `/invocations` and `/jobs/{id}` require the token and fail closed without it. The token is one shared secret with no
   caller identity, and it is read at start-up. `SQUAD_ALLOW_UNAUTHENTICATED=1` opens both endpoints and is for demos only. See
   [API authentication](security/hardening.md#api-authentication) and [Threat model](security/threat-model.md).
2. **The sandbox falls back to a local process, but only on purpose.** pam refuses to start without `SANDBOX_NAMESPACE` unless
   `ALLOW_LOCAL_SANDBOX=1` is set. The kind example sets it, so the demo runs without isolation. See [pam](agents/pam.md#sandbox).
3. **Job state and de-duplication are per replica unless Redis is configured.** Without `SESSION_STORE_URL`, the job store and the in-flight claim
   are in memory. The in-process store holds 10,000 entries and evicts the least recently used one, so it can evict a live claim. Use Redis for
   production; the chart refuses more than one michael replica while `sessionStore.url` is empty. The webhook de-duplication record and the debounce
   are still in memory. See [Scaling and upgrades](deployment/scaling-upgrades.md).
4. **The whole Secret is mounted into every agent pod.** A compromised agent can read every key. See [Secrets](deployment/secrets.md#what-each-pod-can-read).
5. **Config maps are readable by darryl.** Their values reach the model after redaction. See [RBAC](deployment/rbac.md).
6. **Sandbox pod TTL is not applied.** A crashed run can leave a pod until its deadline. See [pam sequence](architecture/pam-sequence.md).
7. **Secret providers `file` and `vault` do not work.** `file` is refused by the factory, and `vault` is a stub. See [Secrets](deployment/secrets.md#providers).
8. **Accepted risks are organisation-only.** ADR 0013 says organisation or registry; the code and the documentation say organisation only, which is the
   narrower rule. See [recipe 7](configuration/recipes.md#7-accepted-findings).

### Features declared but not applied

These keys are accepted by the schema, appear in the reference, and have no effect at run time. Do not rely on them until the gap is closed.

- `review.max_diff_bytes`.
- `llm.base_url`. The gateway URL comes from the environment (`LLM_BASE_URL`). `llm.allowed_models` is applied.
- `implementer.sandbox.image`, `cpu` and `memory` (the chart's environment variables are used).
- Attachments: validated by the contract for pam, but not sent to the model.
- `cost_hint` in results is always `null`.

The keys removed by ADR 0013 are listed in the Unreleased section of the `CHANGELOG.md` at the repository root. The reference
([Configuration](reference/configuration.md)) shows only the keys that the schema accepts.

### Deployment and documentation drift

- The air-gapped example relies on `EGRESS_PROXY_URL`, which the model client does not read. Model traffic needs `HTTPS_PROXY` settings.
- No extra CA bundle setting exists for private certificate authorities. TODO(architect): decide whether to add one.
- Extra agents cannot be deployed by the chart. TODO(architect): decide whether the chart should render them.
- The chart does not fail when `api.tokenSecret` is empty and `api.allowUnauthenticated` is false. The agents refuse requests, so the install is
  safe, but `helm install` succeeds. A `fail` in the template would make the default values fail to render, so it was not added.
- The CLI differs from the brief: there is `squad invoke`, `squad review` and `squad config schema|validate|explain|init`, not `squad <agent> review <target>`.
- Finding `category` is a free string in the model, not the enumeration the brief lists. Prompts use the brief's values.
- The result `stats` carry `input_tokens` and `output_tokens`, not a single `tokens` field, and no wall-clock field. `trial_review.sh` times the call itself.
- The `config.org` and `config.projects` blocks embedded in every values file are validated against the schema by
  `tests/test_values_examples_config.py`.
- By design, `/ready` reports only that the agent specification loaded. It does not call the model gateway, so a gateway outage does not
  make a pod unready. See [HTTP contract](architecture/contract.md).
- `docs/BRIEF.md` is the original design and still names some keys that were removed. It is kept as the record of the brief.

### Evaluation and testing

- The evaluation set has four golden cases, all for `jim` and `angela`. No case covers `dwight`, `darryl` (including the three troubleshooting scenarios in the brief) or `pam` (the feature-with-change-request scenario).
- No live model evaluation has been run. Replay results measure the pipeline only. The first operational test is the first live measurement, and its
  provider responses are meant to become conformance fixtures.
- The kind smoke test has not run end to end; see the packaging validation record.
- The arm64 image has been built (emulated) but not run.

## Next steps

1. Run the [first operational test](operations/first-operational-test.md) on one real project: dry runs first, then posting, with the acceptance
   criteria and the results table filled in.
2. Record the provider responses from that test as conformance fixtures, so the GitLab and GitHub providers are tested against live shapes
   (context lines, renames, multi-line ranges, the GitHub App identity).
3. Use Redis for the session store and add a claim-store test for eviction before allowing more than one michael replica.
4. Split the Secret by agent and move the webhook secrets to their own Secret by default.
5. Decide the deferred items in [ADR 0013](decisions/0013-operational-readiness.md#decision): live-model evaluation and golden cases for dwight,
   darryl and pam, one review context shared across specialists, prompt caching, supersede-cancel of in-flight runs, and a persistent job queue.
   These wait for evidence from the operational test.
6. Apply or remove each declared-but-unapplied key in the list above (`review.max_diff_bytes`, `llm.base_url`, the sandbox image settings).
7. Run the kind smoke test and the arm64 image on a host that can create a cluster, and record the results in the validation page.
8. Decide the open points listed in the [decisions index](decisions/index.md#open-points-raised-in-the-adrs).

## Open decisions

For the architect (TODO(architect)):

- Whether the shared bearer token on `/invocations` is the final model, or whether per-caller identity or mTLS is required (the token is
  implemented and fail closed; the choice of layer is open).
- Whether pam is allowed to run on the local backend in a cluster at all. ADR 0013 allows it only with `ALLOW_LOCAL_SANDBOX=1`.
- Whether the chart should deploy extra agents, and how their prompts and knowledge are mounted.
- Whether the image should trust a mounted private CA bundle.
- Whether `review.ignore_globs` should be organisation-only (ADR 0003). Accepted risks are organisation-only since ADR 0013.
- Whether the orchestrator should ever submit a formal approval (ADR 0010).
- Whether sandbox pods should become Jobs so that orphans are deleted (ADR 0005).
- Whether the chart should refuse an empty `api.tokenSecret` at render time, which needs a placeholder default for the demo values.
