# Adding a VCS provider

A provider adapts one code host (for example Bitbucket or Gitea) to the squad. Agents and tools talk only to
the `VcsProvider` protocol, so adding a host means implementing that protocol, passing the shared conformance
suite, and connecting the provider to configuration and to webhooks. The GitLab and GitHub providers are the
reference implementations.

This is a change to the platform. Record the decision in an ADR first ([process](../contributing/index.md#adr-process)).

## 1. Implement the protocol

Create `src/code_squad/_common/vcs/<host>.py`. The protocol is `VcsProvider` in `_common/vcs/base.py`. It needs:

- `name` (a short string used in metrics and logs) and `capabilities`, a `frozenset[Capability]`.
- Change requests: `whoami`, `get_change_request`, `get_diff_refs`, `get_diff`, `list_changed_files`.
- Repository reads: `read_file`, `list_tree`, `search_repo`, `get_default_branch`, `is_protected`, `clone_url`,
  `git_credentials`.
- Comments and reviews: `list_comments`, `post_inline_comments`, `post_summary`, `upsert_comment`,
  `resolve_thread`, `submit_review_verdict`.
- Statuses and CI: `set_status`, `list_ci_runs`, `list_ci_jobs`, `get_job_log`.
- Writes for implementer runs: `create_branch`, `create_change_request`, `add_labels`, `request_reviewers`.
- Issues: `get_issue`, `comment_on_issue`.
- Introspection: `rate_limit`.

Rules that the suite and the platform depend on:

- Errors are typed: `NotFoundError`, `RateLimitedError` (with `retry_after`), `StaleHeadError`,
  `ProtectedBranchError`, and `CapabilityError` for an unsupported operation. Never fail silently on a missing
  capability; raise `CapabilityError` and let the caller record the fallback.
- Inline comments are anchored to `head_sha`. If the head moved, raise `StaleHeadError` rather than post at the
  wrong line.
- Pagination is followed with a cap. Timeouts and retries use the shared `HttpClient` (`_common/vcs/http.py`),
  which already handles `429`, `5xx`, `Retry-After` and back-off.
- Credentials never appear in URLs, logs or exceptions. `git_credentials` returns a pair used only by the
  sandbox's askpass file.
- `set_status` uses the state names of `StatusState`, mapped to the host's values.

Use the existing modules as the model: `gitlab.py` for a discussion-based host, `github.py` for a host with
check runs, batched reviews and an App installation flow. `diff.py` parses unified diffs into hunks; reuse it.

## 2. Register the provider

| Place | Change |
| --- | --- |
| `_common/vcs/factory.py` | `resolve_kind` and `build_provider` return the new provider for its name. |
| `_common/config/schema.py` | Add the name to the `Literal` of `VcsConfig.provider` and `ProjectEntry.provider`. |
| `_common/contract.py` | Add the name to `ProjectConfigOverride.vcs_provider`. |
| `_common/secrets/factory.py` | Map the default API host to the provider in `_HOST_PROVIDER` and `_DEFAULT_BASE_URL`, when the host has a public default. |
| `_common/webhooks.py` and `michael/gateway.py` | Add the provider to `Provider`, `PROVIDERS` and the verifier and parser dispatch. Implement signature verification with a constant-time comparison and a delivery id. |
| `deploy/helm/code-squad/templates/ingress.yaml` and `values.yaml` | Add a `webhooks.<name>.enabled` flag and a path, if the chart should expose it. |

Run `just docs-gen` after the change. The capability matrix (`reference/vcs-capabilities.md`) is generated from the
provider classes, so add the new column to `scripts/gen_docs.py` (`render_vcs_capabilities`) and to the
generation test.

## 3. Pass the conformance suite

The suite is `src/code_squad/_common/vcs/conformance/suite.py`. It holds one check per behaviour (`ALL_CHECKS`):
identity, change request metadata, fork flag, diff refs, diff and hunks, stale head, paginated changed files,
file and tree reads, search, default branch, comments, inline posting, statuses, resolve, CI, branches and
change requests, and capability errors. Each check runs against a backend and must pass.

The test is `tests/vcs/test_conformance.py`. It runs every check against three backends, parametrised by
`BACKENDS`: the in-memory fake, GitLab and GitHub. Each HTTP backend replays recorded responses through `respx`
(see `tests/vcs/recorded.py`), so the suite needs no network.

To add a provider:

1. Add its name to `BACKENDS` and to the `backend()` context manager in `tests/vcs/test_conformance.py`.
2. Add a recorder for its API in `tests/vcs/recorded.py`. Record the responses the scenario needs, using the
   fake values from `_common/vcs/conformance/scenario.py`, and no real tokens or hosts.
3. Add provider-specific tests in `tests/vcs/test_<host>.py` for error mapping, rate limits, pagination and the
   webhook verifier.
4. Run `just test tests/vcs` until the conformance suite is green for all four backends.

## 4. Document it

- Add a page under `docs/vcs/` in the style of [GitLab](gitlab.md): the bot identity, the token scopes, the
  webhook setup and the troubleshooting table.
- Add the provider to the navigation in `mkdocs.yml`.
- Add an entry to the `vcs` section of the changelog.

## Checklist

- [ ] ADR written and accepted.
- [ ] Protocol implemented; capabilities declared honestly.
- [ ] Factory, schema, contract, secrets mapping and webhook dispatch updated.
- [ ] Conformance suite green for fake, the existing hosts and the new host.
- [ ] Webhook verifier uses a constant-time comparison; tests cover a bad signature and a duplicate delivery.
- [ ] Capability matrix regenerated; `just docs-check` clean.
- [ ] Documentation page and navigation entry added; `just docs` builds with `--strict`.
