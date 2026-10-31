---
title: OWASP Top 10 (2025) for review
source: OWASP Top 10:2025 (top10.owasp.org/2025)
version: OWASP Top 10:2025
reviewed: 2026-10
---

## Scope

The ten web application risk categories in OWASP Top 10:2025, with review guidance per category. Use this file to organise findings at category level and to choose the detailed topic file for depth. The category id is a reference; the rule id is the `SEC-*` rule in the topic file. Representative CWEs are listed for orientation and are not exhaustive. Map each finding to the most specific CWE that the evidence supports.

Edition check: the 2025 edition lists A03 Software Supply Chain Failures as new and folds SSRF into A01. Use this edition, not the 2021 edition, unless the project states otherwise.

## Rules

### SEC-ACCESS-000 — A01:2025 Broken Access Control

- **Look for:** missing authorisation on any route, action, or record; checks on the client only; IDOR through predictable identifiers; path traversal; CORS allowing untrusted origins with credentials; SSRF that reaches internal resources.
- **Representative CWEs:** CWE-22, CWE-284, CWE-285, CWE-352, CWE-639, CWE-862, CWE-863, CWE-918.
- **Evidence:** the endpoint, the missing check, and the resource accessed by a different principal.
- **Default severity:** high (critical for admin functions or cross-tenant data).
- **Detail:** see `ssrf-path-traversal.md` for SSRF and path traversal, and `owasp-api-top10.md` (API1, API3, API5) for object-level and function-level authorisation.

### SEC-CONFIG-000 — A02:2025 Security Misconfiguration

- **Look for:** debug modes enabled in production; default credentials; verbose errors; permissive CORS; unnecessary features or ports; missing security headers; XML parsers with external entities enabled; cloud storage with public access; containers running as root.
- **Representative CWEs:** CWE-16, CWE-611, CWE-942, CWE-1188.
- **Evidence:** the setting, the file, and the environment it reaches.
- **Default severity:** medium; high for default credentials or public data stores.
- **Detail:** `docker-k8s-hardening.md`, `java.md` (Spring Security and actuator), `node-react.md`.

### SEC-SUPPLY-000 — A03:2025 Software Supply Chain Failures

- **Look for:** dependencies with known vulnerabilities; unpinned or unverified build inputs; compromised or typosquatted packages; CI actions and images referenced by mutable tags; install scripts; missing SBOM or provenance for released artefacts.
- **Representative CWEs:** CWE-1104, CWE-1395, CWE-494, CWE-829, CWE-427.
- **Evidence:** the manifest or workflow line, the package and version, and the advisory or missing verification.
- **Default severity:** depends on triage; see `dependency-triage.md`.
- **Detail:** `supply-chain-ssdf-slsa.md`, `dependency-triage.md`.

### SEC-CRYPTO-000 — A04:2025 Cryptographic Failures

- **Look for:** weak algorithms (MD5, SHA-1 for security purposes, DES, RC4); ECB mode; static or reused IVs or nonces; homemade cryptography; passwords hashed with fast hashes; missing TLS certificate validation; cleartext transmission of sensitive data.
- **Representative CWEs:** CWE-259, CWE-295, CWE-311, CWE-319, CWE-321, CWE-327, CWE-328, CWE-329, CWE-338.
- **Evidence:** the algorithm, mode, and key or IV source.
- **Default severity:** high for passwords, keys, and transport; medium for non-security hashing misuse.
- **Detail:** `crypto.md`.

### SEC-INJECT-000 — A05:2025 Injection

- **Look for:** untrusted input concatenated into SQL, NoSQL, OS commands, LDAP, XPath, template engines, expression languages, or HTML.
- **Representative CWEs:** CWE-77, CWE-78, CWE-79, CWE-89, CWE-94, CWE-917.
- **Evidence:** the source, the sink, and the missing neutralisation or parameterisation.
- **Default severity:** critical when reachable without authentication; high otherwise.
- **Detail:** `injection.md`, `xss-csrf.md`, `java.md`, `node-react.md`.

### SEC-DESIGN-000 — A06:2025 Insecure Design

- **Look for:** missing threat model for sensitive flows; business logic that allows abuse (coupon stacking, unbounded retries, race conditions in balance updates); no rate limits on authentication or expensive operations; trust decisions made by the client.
- **Representative CWEs:** CWE-256, CWE-501, CWE-522, CWE-657, CWE-770.
- **Evidence:** the flow, the abuse case, and the missing control.
- **Default severity:** medium; high for payment, identity, or privilege flows.
- **Detail:** `authn-session.md` for authentication flows; `owasp-api-top10.md` API4 and API6.

### SEC-AUTHN-000 — A07:2025 Authentication Failures

- **Look for:** weak or missing brute-force protection; default or weak passwords accepted; session identifiers in URLs; session not rotated at login; tokens that do not expire; missing MFA on privileged actions.
- **Representative CWEs:** CWE-287, CWE-306, CWE-307, CWE-384, CWE-521, CWE-613, CWE-798.
- **Default severity:** high.
- **Detail:** `authn-session.md`.

### SEC-INTEG-000 — A08:2025 Software or Data Integrity Failures

- **Look for:** deserialisation of untrusted data; auto-update or plugin loading without signature verification; CI/CD pipelines that trust unverified artefacts; unsigned or unchecked downloads.
- **Representative CWEs:** CWE-345, CWE-353, CWE-426, CWE-494, CWE-502, CWE-829.
- **Default severity:** high for deserialisation of untrusted input.
- **Detail:** `deserialisation.md`, `supply-chain-ssdf-slsa.md`.

### SEC-LOG-000 — A09:2025 Security Logging and Alerting Failures

- **Look for:** authentication, authorisation, and input-validation failures not logged; logs that contain secrets or personal data; no alerting path for security events; log injection.
- **Representative CWEs:** CWE-117, CWE-223, CWE-532, CWE-778, CWE-779.
- **Default severity:** medium; high when secrets are logged.
- **Detail:** `secrets-logging.md`.

### SEC-ERR-000 — A10:2025 Mishandling of Exceptional Conditions

- **Look for:** fail-open behaviour on errors in authentication or authorisation; error messages that reveal stack traces, queries, or internal paths; unhandled exceptions that leave partial state; resource exhaustion without limits.
- **Representative CWEs:** CWE-209, CWE-234, CWE-390, CWE-460, CWE-703, CWE-755.
- **Evidence:** the catch or fallback path and the state it leaves.
- **Default severity:** high for fail-open on authorisation; medium for information disclosure.

## How to apply in review

1. Map each finding to one category above, then to the most specific CWE and rule id.
2. Prefer findings with a concrete attack path in the diff. Omit theoretical categories that the change does not touch.
3. Cite the file, line, and the category id together in the finding.
4. For categories the diff does not touch, do not report. State coverage limits in the summary when relevant.
5. Use `cwe-top25.md` to prioritise where several categories apply.
