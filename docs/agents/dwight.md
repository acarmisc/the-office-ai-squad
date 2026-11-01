# dwight: security reviewer

`dwight` assesses the security posture of a change: application code in any language present in
the diff, configuration, dependency manifests, Dockerfiles and CI files, secrets exposure,
authentication and authorisation, input handling, cryptography and supply chain. For dependencies
it queries live vulnerability sources. It runs on every review unless disabled.

| Item | Value |
| --- | --- |
| Role | sec-reviewer |
| Modes | `review` |
| Default model | `sonnet-5-5` |
| Max tokens per call | 8192 |
| Max model turns | 30 |
| Writes externally | `publish_review` only, and only when posting is enabled |

## Triggers

- Always: `routing.always_run` defaults to `[dwight]`, so `michael` routes every review to it. A
  lower layer cannot remove it.
- `michael` runs `dwight` in full scope when the risk tier is high.
- A `/squad sec` comment on a change request starts a security-only run through `michael`.
- Direct calls with `POST /invocations`, `mode: "review"`.

## Inputs and tools

| Tool | Class | Purpose |
| --- | --- | --- |
| `get_review_context` | read | Change metadata, diffs, changed files, existing comments. |
| `read_file`, `search_repo`, `list_tree` | read | Code reading, reachability checks. |
| `get_project_skills`, `load_skill`, `read_knowledge` | read | Project guidance and the security pack. |
| `parse_dependencies` | read | Deterministic parser for lockfiles, manifests and Dockerfile base images. |
| `lookup_vulnerabilities` | read | OSV batch query, then detail; GitHub advisories as a secondary source. |
| `lookup_cve` | read | NVD record for one CVE, enriched with CISA KEV membership and EPSS. |
| `search_advisories` | read | Recent advisories for an ecosystem, package or keyword, within the allow-listed hosts. |
| `publish_review` | external write | Posts findings. Refused in dry run. |
| `finish` | read | Ends the run with a verdict. |

Dependency parsers cover `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `pom.xml`,
`gradle.lockfile`, `build.gradle` and `build.gradle.kts`, `requirements*.txt`, `uv.lock`, and
`Dockerfile` base images. A Dockerfile base image has no vulnerability feed here, so it is treated
as unverified data.

Every tool output from an external source is wrapped as untrusted content. The tools use a cache,
rate-limit back-off, timeouts and the optional egress proxy `EGRESS_PROXY_URL`. There is no tool that
fetches an arbitrary URL.

## Method

1. Build a short threat model of the change: entry points, trust boundaries, sensitive data and
   privileges.
2. Load only the knowledge topics that match the threat model. For a dependency change,
   `security/dependency-triage` comes first.
3. Confirm each candidate weakness in the head version. A weakness that needs an attacker who already
   holds the privilege it would grant is not a finding.
4. Map each finding to a CWE. Dependency findings also cite the advisory or CVE id.
5. Never print a secret value. Report the location, the kind and the rotation advice.

Dependency ranking: CISA KEV first, then high EPSS, then CVSS, then reachability (whether the
vulnerable function is used with attacker-controlled input).

## Verdict guard and offline mode

Advisory data can be missing: a source is down, switched off, rate limited, or a package has no
resolved version. In that case the lookup output starts with `VULNERABILITY DATA UNAVAILABLE/UNVERIFIED`
and the run is flagged. After the model finishes, a guard checks the change. If it touches a dependency
manifest, Dockerfile or build plugin, and the data was unavailable or no lookup ran, the guard acts:

- `security.offline_mode: low_confidence` (default): an `approve` becomes `comment`, with the warning
  "vulnerability data unavailable/unverified; approve withheld".
- `security.offline_mode: fail_incomplete`: the status and verdict become `incomplete`.

The guard only weakens a result; it never raises one. Publishing applies the same rule before the
approval is submitted, so a withheld approve is posted as a comment with commit status `pending`.

## Outputs

The smoke-stub output below shows the result shape only. It was produced by the scripted model
of the offline fake LLM, not by a real review. A real review adds findings with `CWE-` references.

```json
{
  "agent": "dwight",
  "status": "complete",
  "verdict": "comment",
  "summary": "Smoke run: security reviewer completed its scripted pass. No findings were raised and nothing was published.",
  "findings": [],
  "stats": {"iterations": 2, "input_tokens": 20, "output_tokens": 10, "tool_calls": {"read_knowledge": 1, "finish": 1}},
  "posted": {"notes": 0, "discussions": 0, "status": null, "urls": []},
  "warnings": []
}
```

## Knowledge

Pack `security/` with the index `security/index`. Topics: `security/owasp-top10`,
`security/cwe-top25`, `security/owasp-api-top10`, `security/owasp-asvs`,
`security/owasp-llm-top10`, `security/injection`, `security/xss-csrf`, `security/ssrf-path-traversal`,
`security/deserialisation`, `security/authn-session`, `security/secrets-logging`, `security/crypto`,
`security/docker-k8s-hardening`, `security/supply-chain-ssdf-slsa`, `security/node-react`,
`security/java`, `security/dependency-triage`. Each rule has a stable id prefix (for example
`SEC-INJECT-`, `SEC-DEP-`). The prompt forbids invented ids.

The ASVS topic is marked unverified for its edition. Check the edition before relying on control ids.

## Configuration that affects dwight

| Key | Default | Effect |
| --- | --- | --- |
| `routing.always_run` | `[dwight]` | Lower layers may only add agents. |
| `agents.dwight.enabled` | `true` | Disabling it is refused for `dwight` when it is in `always_run`. |
| `agents.dwight.model`, `fallback_model`, `max_tokens`, `max_iterations`, `temperature` | built-in | As for other agents. |
| `security.sources.osv`, `nvd`, `ghsa`, `kev`, `epss` | all `true` | Each source switched on. A switched-off source marks the data unavailable. |
| `security.allowed_hosts` | `api.osv.dev`, `services.nvd.nist.gov`, `api.github.com`, `www.cisa.gov`, `api.first.org` | Hosts the clients may contact. Organisation only. |
| `security.cache_ttl_seconds` | `21600` | Advisory cache lifetime, per run in this version. |
| `security.severity_mapping.*` | `kev_is_blocker` true; CVSS 9.0 and 7.0; EPSS 0.1 | Thresholds that map advisory data to severity. Lower layers may only lower them. |
| `security.offline_mode` | `low_confidence` | `fail_incomplete` makes missing data an incomplete run. |
| `security.accepted_risks` | `[]` | Accepted advisories with an expiry date. Expired entries are ignored with a warning. |
| `security.local_scanners.*` | all `false` | Setting is accepted, but gitleaks, semgrep and trivy are not wired yet. |
| `EGRESS_PROXY_URL` (environment) | unset | Outbound proxy for advisory calls. |
| `NVD_KEY_SECRET` name `nvd-api-key` (secret) | optional | Raises the NVD rate limit. Without it the client waits 6 seconds between requests. |
| `GHSA` token secret `ghsa-token` (secret) | optional | Used for GitHub advisory queries. |

## Limits

- Advisory coverage depends on the sources. OSV and GitHub advisories cover most ecosystems; NVD
  adds CVSS and CWE; KEV and EPSS add exploitation signals. A package with no feed is unverified.
- Reachability is a search, not a call graph. The prompt asks the model to state the search scope
  when it says "not reachable". Transitive use through a framework is reported as possible, not
  excluded.
- Local scanners are not wired, so secret scanning by pattern is the job of the model and the
  change-level risk check in `michael`.
- Every run builds its own intelligence client, so the cache and the NVD rate window are per run.

## Known weaknesses

- Accepted-risk matching uses the references the model supplies. An accepted id cited on an
  unrelated finding can hide that finding. The warning keeps the drop visible.
- A lockfile finding can be demoted by `review.ignore_globs` (which include `**/package-lock.json`),
  but it still counts towards the verdict.
- Model-only checks (for example authorisation logic) depend on reading the surrounding code.

## How to evaluate

The eval set has no security-only case yet. Use the dependency-triage and secret cases as the next
step (see [Testing](../testing/index.md)). Unit tests cover the parsers, the guard, the offline
behaviour and the intelligence clients with recorded responses.
