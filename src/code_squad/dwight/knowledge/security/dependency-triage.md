---
title: Dependency vulnerability triage and severity mapping
source: CISA Known Exploited Vulnerabilities (KEV) catalog and BOD 22-01; FIRST EPSS model documentation; FIRST CVSS v3.1 and v4.0 specifications (severity rating bands); OSV.dev; NVD CVE API 2.0; OWASP Top 10:2025 A03
version: CVSS v4.0 rating bands (same bands as v3.x); EPSS v4 (score range 0 to 1, 30-day exploitation probability); CISA KEV (live catalog)
reviewed: 2026-10
unverified-edition: true
---

## Scope

How to rank and report known vulnerabilities in dependencies touched by a change, how to map them to the review severity scale, and what to do when vulnerability data is unavailable. Use this file whenever the diff changes a manifest, lockfile, base image, or build plugin. Applies to vulnerability lookups by `lookup_vulnerabilities` and `lookup_cve`, and to local scanner output when present.

## Rules

### SEC-DEP-001 — Ranking order for dependency findings

Rank dependency findings in this order, highest first:

1. **In CISA KEV** (known exploited). Always ranks above unexploited items with a higher CVSS.
2. **High EPSS** (probability of exploitation in the next 30 days). Use the score and percentile as reported.
3. **CVSS base severity** (v4.0 preferred; v3.1 when v4.0 is absent). Use as a tiebreaker, not a sole driver.
4. **Reachability.** Is the vulnerable function, class, or endpoint used by this code path, and is the input attacker-controlled?

- **Why it matters:** CVSS measures theoretical severity. KEV and EPSS measure real-world exploitation. Reachability decides whether the risk applies here.
- **Evidence:** the package, installed version, advisory id (CVE, GHSA, OSV id), KEV membership, EPSS score, and the reachability argument with file and symbol.
- **Default severity:** derived by SEC-DEP-002.

### SEC-DEP-002 — Severity mapping to review scale

The review scale is the contract scale: `blocker`, `major`, `minor`, and `nit`. Use the first row that matches. The thresholds are the defaults of `SeverityThresholds` in `dwight/intel/triage.py`, which the `security.severity_mapping` configuration sets.

| Condition | Review severity |
|---|---|
| In CISA KEV, with `kev_is_blocker` true (default) | blocker |
| CVSS base 9.0 to 10.0 | blocker |
| CVSS base 7.0 to 8.9 | major |
| EPSS at or above 0.10 (any CVSS) | major |
| CVSS base 4.0 to 6.9 | minor |
| CVSS base 0.1 to 3.9 | nit |
| Advisory with no CVSS and no exploit data | nit |

- **Note:** the lookup output states the suggested severity and confidence for each advisory. Use that value. EPSS thresholds are guidance: state the EPSS value used in the finding.
- **Reachability:** the suggested severity does not depend on reachability. Record reachability as evidence (SEC-DEP-003) in the rationale. Do not lower a suggested severity. A reviewer may raise it with a stated reason, for example an advisory with no CVSS that is reachable from a request path may be raised to `minor`.
- **Confidence:** when lookups failed or reachability is unknown, set `confidence: low` and apply the offline rule in SEC-DEP-004.
- **Verdict:** the verdict follows from the severities. Any `blocker` gives `request_changes`. Major findings at or above `review.verdict.major_threshold` (default 1) give `comment`. Otherwise the verdict is `approve`, subject to SEC-DEP-004.

### SEC-DEP-003 — Reachability evidence

- **Look for:** whether the vulnerable symbol, configuration, or feature is used. Examples: a vulnerable XML parser used only with trusted local files; a vulnerable template engine used only for static templates; a vulnerable feature flag disabled in configuration.
- **How to show it:** search the repository for the import, class, function, or configuration key named in the advisory. Cite each hit. If no hit exists after search, state "not reachable in the searched code" and state the search scope.
- **Limits:** a transitive dependency with no direct import can still be reachable through a framework. Say so rather than declaring it unreachable.
- **Default severity:** not a finding by itself; affects SEC-DEP-002.

### SEC-DEP-004 — Offline and restricted-egress rule

- **Rule:** when vulnerability data cannot be retrieved (lookups fail, time out, or are blocked), mark each affected finding `confidence: low` and state "vulnerability data unavailable or unverified" in the summary.
- **Hard rule:** never return an `approve` verdict for a diff that touches dependencies when vulnerability data is missing. Return `request_changes` or `comment`, and name the missing check.
- **Why it matters:** an approval based on missing data looks like an assurance that did not happen.
- **Default severity:** not applicable; governs the verdict.

### SEC-DEP-005 — Local scanners

- **Rule:** when a local scanner (for example a dependency or container scanner) is available and runs, use its output as untrusted input. Normalise results to the finding schema, deduplicate against lookup results, and cite the scanner name and version.
- **Rule:** scanner output does not override KEV or EPSS data. Use the ranking in SEC-DEP-001 regardless of source.
- **Default severity:** as SEC-DEP-002.

### SEC-DEP-006 — Version and fix availability

- **Look for:** whether a fixed version exists, whether it is semver-compatible with the current range, and whether it has a breaking change in the diff.
- **Report:** the first fixed version from the advisory, and the change needed in the manifest or lockfile. Do not recommend an unpinned or unreleased version.
- **Default severity:** not a finding by itself.

### SEC-DEP-007 — Unpinned and unknown-version packages

- **Look for:** dependencies with no resolved version in the lockfile, floating ranges (`*`, `latest`, `>=`) for runtime packages, and base images without digests.
- **Why it matters:** the vulnerable version cannot be determined, so triage is impossible.
- **Default severity:** minor for production dependencies; nit for dev tooling.

### SEC-DEP-008 — Redaction and reporting

- **Rule:** report the package name, version, advisory id, and file location. Do not print tokens found in lockfiles, registry URLs with credentials, or `.npmrc` and `settings.xml` content.
- **Rule:** if a manifest or lockfile contains a credential, report its location and treat it under `secrets-logging.md`.
- **Default severity:** as the credential rule.

### SEC-DEP-009 — Ecosystem notes

- **npm and pnpm:** check `package-lock.json`, `pnpm-lock.yaml`, and `yarn.lock`; note install scripts (see `node-react.md`).
- **Maven and Gradle:** resolve effective versions where possible (parent POMs and BOMs can override declared versions). State when the resolved version is uncertain.
- **Python:** `requirements*.txt` and `uv.lock`; note unpinned requirements.
- **Containers:** base image tags and digests from `Dockerfile` `FROM` lines.
- **Default severity:** as SEC-DEP-002.

## How to apply in review

1. Parse the changed dependency set, including versions, from lockfiles where possible.
2. Look up advisories for each new or changed version. Record the lookup source and time.
3. Apply the ranking (SEC-DEP-001), the reachability check (SEC-DEP-003), and the mapping (SEC-DEP-002). Derive the verdict from the severities.
4. If lookups failed, apply SEC-DEP-004 before writing the verdict.
5. Report each finding with the package, version, advisory id, KEV and EPSS status, reachability evidence, and first fixed version. Redact secrets.
