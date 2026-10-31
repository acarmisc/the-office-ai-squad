---
title: Secrets management and sensitive data in logs
source: OWASP Secrets Management Cheat Sheet; OWASP Logging Cheat Sheet; OWASP Top 10:2025 A09 and A02; CWE-798, CWE-532, CWE-200
version: OWASP Top 10:2025; OWASP Cheat Sheets (current web versions)
reviewed: 2026-10
---

## Scope

Hard-coded and leaked secrets (API keys, tokens, passwords, private keys, connection strings), how secrets are supplied to applications, and sensitive data written to logs, errors, analytics, and telemetry. Applies to source, configuration, CI files, container images, and runtime output.

Reporting rule for this whole pack: **report the location only. Never print, quote, partially reveal, or hash-echo a secret value in a finding, summary, or log.** Include the file, line, secret type, and a masked hint at most (for example "AWS access key id pattern, last 4 characters"). If you cannot tell whether a value is real, say so.

## Rules

### SEC-SECRETS-001 — Secret committed to source or history

- **Look for:** API keys, tokens, passwords, private keys (`BEGIN PRIVATE KEY`), cloud credentials, webhook URLs with tokens, connection strings with credentials, `.env` files with real values, and keys in test fixtures.
- **Why it matters:** source is copied widely and kept in history. Removing the line does not remove the secret from history.
- **Evidence:** file and line; secret type; whether it looks like a placeholder (for example `changeme`, `xxx`, `example`).
- **Action advice:** rotate the secret, do not reuse it, and remove it from history using the platform's tooling. Rotation is required even when the repository is private.
- **Default severity:** critical for production credentials; high for others; low for clearly fake placeholders.
- **CWE:** CWE-798, CWE-540, CWE-312.

### SEC-SECRETS-002 — Secret in configuration with a default

- **Look for:** configuration defaults such as `password=admin`, `secret=dev`, or a fallback secret used when the environment variable is missing; application start without failing on missing secrets.
- **Good:** fail fast when a required secret is missing; no defaults for credentials.
- **Default severity:** high.
- **CWE:** CWE-1188, CWE-798.

### SEC-SECRETS-003 — Secrets in CI and build logs

- **Look for:** `echo` or `set -x` printing variables; secrets passed as command-line arguments (visible in process listings and logs); secrets written to build artefacts; unmasked variables in CI settings.
- **Good:** masked and protected CI variables; pass secrets through environment or stdin; disable command echo around secret use.
- **Default severity:** high.
- **CWE:** CWE-532, CWE-214.

### SEC-SECRETS-004 — Secrets baked into images or artefacts

- **Look for:** `ENV` or `ARG` in Dockerfiles with secret values (persisted in image metadata and layers); `COPY` of files containing secrets; secrets in front-end bundles (see `node-react.md`); secrets in jar or wheel resources.
- **Good:** inject at runtime from a secret store; use build secret mounts for build-time needs.
- **Default severity:** high.

### SEC-SECRETS-005 — Secret storage and access

- **Look for:** secrets stored in plain database columns; secrets shared between environments; secrets readable by all services; no rotation mechanism.
- **Good:** a secret manager or encrypted store with per-service access, versioning, and rotation.
- **Default severity:** medium to high.

### SEC-SECRETS-006 — Secrets in URLs and query strings

- **Look for:** tokens or keys as query parameters; secrets in redirect URLs; reset or magic-link tokens in logged URLs.
- **Why it matters:** URLs appear in server logs, proxies, browser history, and Referer headers.
- **Default severity:** high.
- **CWE:** CWE-598.

### SEC-SECRETS-007 — Secrets in error output and responses

- **Look for:** stack traces, configuration dumps, or environment listings returned to clients; debug endpoints that show environment variables; error messages that include connection strings.
- **Default severity:** high.
- **CWE:** CWE-209, CWE-200.

### SEC-LOG-001 — Sensitive data in log statements

- **Look for:** logs that include passwords, tokens, session ids, API keys, card numbers (PAN), bank accounts, national ids, health data, full request or response bodies, authorisation headers, and cookies.
- **Why it matters:** logs are retained longer, read by more people, and shipped to third parties (CWE-532).
- **Evidence:** the log call, the variable with sensitive content, and the logger configuration if it is set to log bodies.
- **Good:** log identifiers, not values; redact known fields at the logger; log event names and outcomes.
- **Default severity:** high; critical for credentials or PAN.

### SEC-LOG-002 — Logging of personal data

- **Look for:** email addresses, phone numbers, addresses, and names in info-level logs for routine operations; analytics events carrying free text entered by users.
- **Default severity:** medium.
- **CWE:** CWE-359.

### SEC-LOG-003 — Security events are logged

- **Look for:** failed logins, authorisation denials, permission changes, password changes, and admin actions with no log entry; logs that omit the subject, the time, or the source.
- **Good:** log security events with actor, action, target, outcome, and source; send to a central store with alerting.
- **Default severity:** medium.
- **CWE:** CWE-778.

### SEC-LOG-004 — Log injection

- **Look for:** user-controlled strings written with newlines or control characters into line-based logs; unescaped values in structured logs that a viewer renders as markup.
- **Default severity:** low to medium.
- **CWE:** CWE-117.

### SEC-LOG-005 — Error handling and information disclosure

- **Look for:** exceptions that include SQL, file paths, internal hostnames, or framework versions returned to the caller; error responses that differ by account existence.
- **Default severity:** medium.
- **CWE:** CWE-209, CWE-756.

### SEC-LOG-006 — Telemetry and third-party SDKs

- **Look for:** error reporting, session replay, and analytics SDKs capturing form inputs, URLs with tokens, or request bodies; SDK configuration that disables masking.
- **Good:** mask inputs and sensitive attributes in SDK configuration; scrub URLs before sending.
- **Default severity:** medium to high.

## How to apply in review

1. Grep the diff for secret-like patterns, but treat matches as candidates: confirm context before reporting.
2. Check every new log statement for the variables it prints.
3. Check configuration changes for defaults and for values that should come from a secret store.
4. Report with file, line, and secret type. Redact the value entirely.
5. For a leaked real secret, recommend rotation first, then cleanup. Do not wait for confirmation of use.
