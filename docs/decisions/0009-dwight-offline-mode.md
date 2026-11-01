# 0009 — dwight offline and restricted-egress behaviour and the verdict guard

- Status: accepted
- Date: 2026-11-01

## Context

`dwight` decides security verdicts from vulnerability data that comes from remote
services (OSV, GHSA, NVD, CISA KEV, FIRST EPSS). These services are often unreachable
in restricted networks, rate limited, or disabled by configuration. The brief (7) requires
that a verdict of `approve` is never returned for a diff that touches dependencies when the
data is missing. The model cannot be trusted to enforce this alone: it may skip the lookup
or ignore the instruction.

## Decision

1. **Unavailable data is detected by the tools and flagged on the run.** When a source fails
   (transport error, timeout, host not on the allow-list, rate limit after retries), when a
   source is switched off, when a package has no resolved version, or when a package has no
   vulnerability feed (Docker base images), the lookup output starts with
   `VULNERABILITY DATA UNAVAILABLE/UNVERIFIED` and the run flag `intel_incomplete` is set.
2. **Docker images and unversioned packages count as unavailable data.** This is the
   conservative choice: no feed means no verification. Dependency changes that only touch a
   Dockerfile are therefore treated as degraded.
3. **A verdict guard runs after the model finishes** (`services["result_guards"]`, applied by
   the runtime to the finished result). It treats the run as degraded when the change touches a
   dependency manifest (`dwight.deps.parsers.is_manifest` over the changed files, or every
   change if the changed files are unknown) and either the run flag is set or no lookup tool
   was called at all. Degraded runs are handled as follows:
   - `offline_mode: low_confidence` (default): an `approve` becomes `comment` with the warning
     "vulnerability data unavailable/unverified; approve withheld". Other verdicts keep their
     value and receive the unverified warning.
   - `offline_mode: fail_incomplete`: the status becomes `incomplete` and the verdict
     `incomplete`, with a warning.
4. **The guard only weakens results.** It never raises a verdict. A verdict of
   `request_changes` is kept in both modes.
5. **Accepted risks are a guard too.** An accepted, non-expired entry drops every finding whose
   `rule_id` equals the entry id or whose references mention it as a whole token. Each drop
   produces a warning "accepted risk: <id> until <date>: <reason>". Expired entries are dropped
   when the configuration is loaded, with the loader's warning (ADR 0003), so they are never
   applied. `security_services` filters by date again, for configurations built without the
   loader.
   The verdict is not recomputed after a drop: a `request_changes` stays, and the warning
   tells the author why the finding is absent.
6. **KEV defaults to a blocker suggestion.** `severity_mapping.kev_is_blocker` is true by
   default and tighten-only. A KEV-listed vulnerability maps to `blocker` before CVSS or EPSS
   are consulted.
7. **NVD rate limit without a key.** The NVD client waits 6.0 seconds between requests when no
   `nvd-api-key` secret is available, and 0.6 seconds when one is. The GHSA token
   (`ghsa-token`) is optional. Both secrets are read through the secret provider; a missing
   secret leaves the source running without the key.
8. **Building the services does no network.** The HTTP clients are created lazily and reach a
   host only when a tool calls them. The egress proxy comes from `EGRESS_PROXY_URL`.

## Consequences

- An `approve` on a dependency change is only possible when the lookups ran and returned data,
  or when the change touches no manifest.
- In a restricted network the run completes with `comment` (default) or `incomplete`, and the
  summary names the missing check. This is intended.
- Disabling a source in configuration also marks the data unavailable. The run then cannot
  approve dependency changes. This is intended: the configuration is explicit.
- The guard reads `stats.tool_calls`, which counts every attempted tool call. A failed lookup
  counts as a call, and the unavailable flag covers it.
- Accepted-risk matching relies on the references the model supplies. A model that cites an
  accepted id on an unrelated finding can hide that finding. The warning keeps the drop visible.
  The schema lets lower layers add accepted risks, so a repository's own `.squad/config.yml`
  (read from the target branch, never from the change head) can accept a risk. Restricting
  accepted risks to the org layer is the open follow-up.
- The intelligence services are built per request (ADR 0008), so the TTL caches and the
  NVD throttle live for one run only. Concurrent runs do not share the NVD rate window, and
  the KEV catalogue is downloaded again on every run. A process-wide service keyed by the
  security configuration is the fix; it is open.
- The default `review.ignore_globs` include `**/package-lock.json`. Publishing drops a finding
  whose file matches an ignore glob, so a finding anchored to a lockfile never reaches the
  change request. dwight anchors dependency findings to the manifest that declares the
  dependency (for example `package.json`) for this reason. Whether security reviewers should
  ignore lockfile globs is open.
- Local scanners (gitleaks, semgrep, trivy) are not wired yet. When they are, their failures
  must set the same unavailable flag.
- Publishing is not covered by the guard. `publish_review` computes its own commit status and
  formal review from the findings it receives (see `_common/findings.py`). A dependency change
  with no findings reaches publish only when the model calls it, and the status it posts is
  derived from findings, not from the guarded verdict. This is open: the fix belongs in the
  publish path (`_common/findings.py`), not in this guard.
