# 0011 — VCS abstraction: protocol, capability flags, GitHub App first, no merge

- Status: accepted
- Date: 2026-11-01

## Context

The squad reads change requests, posts reviews and statuses, and lets `pam` push branches and open change requests on
GitLab and GitHub. The two forges differ: GitLab has merge requests, notes and commit statuses; GitHub has pull requests,
review comments, check runs and two kinds of credential. The brief (section 4.7) asks for one interface, an explicit
set of differences, a conformance suite that every provider passes, and no merge capability (section 18).

## Decision

- **One protocol.** `VcsProvider` in `_common/vcs/base.py` is a `typing.Protocol`. It covers identity, change request
  reads, diffs and files, comments, inline comments, the summary upsert, commit statuses, formal verdicts, CI runs, jobs
  and logs, branches, change request creation, labels and reviewers, the default branch, protected branches, issues,
  the rate limit, the clone URL and git credentials. Callers use only this surface.
- **Capability flags.** Each provider declares `capabilities: frozenset[Capability]`. The flags are `check_runs`,
  `commit_status`, `batched_review`, `approve`, `draft_change_request`, `resolve_thread`, `ci_logs`, `issues` and `push`.
  Callers branch on the flags, never on the provider name. `docs/reference/vcs-capabilities.md` is generated from the
  same sets.
- **Capability fallback with a warning.** When a flag is missing, the caller uses the documented fallback and adds a
  warning to the result instead of failing. Examples: without check runs, michael publishes a commit status and records
  `check runs unavailable; used commit status`; a provider that refuses a formal review yields `formal review is not
  supported by this provider`. The fallback for every flag is in the generated page.
- **GitHub App preferred, personal access token as fallback.** `vcs/factory.py` selects the GitHub App (installation
  token, check runs) when an App id and private key are configured, and a token otherwise. The token path has no check
  runs, so it uses commit statuses and records the warning above.
- **Conformance suite.** `_common/vcs/conformance/suite.py` defines `ALL_CHECKS`. `tests/vcs/test_conformance.py` runs every
  check against the fake provider, the GitLab provider and the GitHub provider, the last two on recorded responses with
  `respx`. A new provider is accepted when it passes every check.
- **Never merge.** The protocol has no merge operation, no provider implements one, and no capability names one. The
  tests in `tests/vcs/test_protocol.py` keep that true. Approval is a separate, configured step (`vcs.approve_mode`,
  default `none`). `pam` refuses to push to protected branches (threat model T16).
- **One error model.** Providers raise the shared `VcsError` family (`NotFoundError`, `RateLimitedError`,
  `CapabilityError`, and others) from `vcs/base.py`. The HTTP client counts final failures in
  `squad_vcs_errors_total{provider,operation}`.

## Consequences

- Adding a forge means implementing the protocol, declaring its capabilities, and passing the conformance suite. No
  caller changes are needed.
- A capability gap is visible in the result warnings and in the generated fallback table, not hidden in a branch.
- GitLab and GitHub are tested against recorded responses only. The live hosts have not been exercised (see the
  handoff). Recorded responses prove the request and parsing shapes, not the behaviour of a live server.
- Jira is an issue source for `pam` behind `vcs/issues/`, read only. It is not a forge and is not part of the protocol.
