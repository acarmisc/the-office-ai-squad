# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/) for the application and the chart.

## [0.1.0] - unreleased

First complete version, built milestone by milestone (see `STATUS.md`).

### Added

- **Platform (M0 to M4).** Agent specification and registry, contract models with `extra="forbid"`, fail-closed validation, tool
  policy with classes, posting gate, untrusted-content wrapping, runtime with one retry, `finish` validation and iteration limits,
  FastAPI server with `/ping`, `/ready`, `/metrics`, `/invocations` and `/jobs/{id}`.
- **VCS and findings (M2).** GitLab and GitHub providers (GitHub App and token authentication), the `VcsProvider` protocol with
  capability flags, the shared conformance suite, anchoring, deduplication, idempotent publication and webhook verification.
- **Configuration (M3).** Five layers, tighten-only and org-only merge rules, the project registry with glob matching and profiles,
  repository files from the target branch, hot reload with a safe fallback, provenance, and the `squad config` commands.
- **Skills (M4).** Discovery in `.agents/skills`, `.claude/skills` and `.squad/skills`, precedence, limits, base-branch reading,
  `load_skill`, caching and sanitising.
- **Reviewers (M5 and M6).** `jim` (React), `angela` (Java) and `dwight` (security), with knowledge packs, dependency parsers for the
  supported lockfiles, vulnerability clients with caching and back-off, and the offline verdict guard.
- **DevOps and sandbox (M7 and M8).** `darryl` with review and read-only troubleshooting tools, redaction, namespace allow-lists and a
  Prometheus adapter. `pam` with advisor and implementer modes, the Kubernetes and local sandboxes, a command allow-list and a
  trajectory monitor.
- **Orchestrator (M9).** `michael` with routing, risk tiers, parallel fan-out with timeouts and circuit breakers, aggregation and one
  consolidated publication, and webhook handling for GitLab and GitHub.
- **Packaging (M10).** Container image for all agents, Helm chart with NetworkPolicies, RBAC, ingress for webhooks only and example values,
  Docker Compose with an offline fake LLM, kind scripts and the HTTP smoke test.
- **Documentation and examples (M11).** The documentation set with generated reference pages and validated examples, GitLab and GitHub
  examples, the Backstage catalogue, the image bump script, and the evaluation harness with replay cases.

### Notes

- Known limitations are listed in `docs/HANDOFF.md`. Two of them need attention before production: the webhook routes are not enabled by
  the chart, and the sandbox falls back to a local process when no sandbox namespace is set.
- The container image does not include the optional Redis client, so `SESSION_STORE_URL` with a Redis URL is not usable yet.
