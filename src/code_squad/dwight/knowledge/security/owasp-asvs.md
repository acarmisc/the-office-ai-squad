---
title: OWASP Application Security Verification Standard (ASVS) for review
source: OWASP ASVS 5.0 (owasp.org/www-project-application-security-verification-standard)
version: ASVS 5.0 (levels L1, L2, L3) - edition not confirmed by live search; see unverified-edition
reviewed: 2026-10
unverified-edition: true
---

## Scope

Control families and verification levels of OWASP ASVS, used to phrase requirements that a diff must satisfy and to decide how strict a finding should be. ASVS is a verification standard. Use it to name the requirement a change fails, not to audit an entire application from a single diff.

Edition note: the edition named above is the one this pack targets. The live search could not confirm the exact release date or chapter list. Before citing a specific requirement number, check the requirement id against the ASVS version the project declares. Chapter names below are the ones this pack relies on.

## Rules

### SEC-ASVS-001 — Choose the verification level for the change

- **Look for:** the sensitivity of the data and function touched by the diff.
- **Levels (ASVS):** L1 for all applications as a baseline; L2 for applications handling sensitive data (personal, financial, health); L3 for high-value or safety-critical applications.
- **Use:** state the level assumed. Default to L1 when unknown and say so. Raise the level when the diff handles credentials, payments, personal data, or administrative functions.
- **Default severity:** not a finding; a framing decision for the review.

### SEC-ASVS-002 — Encoding and sanitisation (chapter V1 in ASVS 5.0)

- **Look for:** output encoding absent for the context (HTML, attribute, JavaScript, URL, SQL); input normalised after validation; canonicalisation issues.
- **Maps to:** `injection.md`, `xss-csrf.md`.
- **Default severity:** follows the injection or XSS rule it links to.

### SEC-ASVS-003 — Validation and business logic (chapter V2)

- **Look for:** server-side validation missing for types, length, format, and range; business rules enforced only in the client; ordering or race conditions in multi-step logic.
- **Default severity:** medium; high for money or access.

### SEC-ASVS-004 — Web frontend and file handling (chapters V3, V5)

- **Look for:** frontend security controls treated as sufficient; file uploads without type, size, and name checks; uploaded files served from the application origin.
- **Maps to:** `xss-csrf.md`, `ssrf-path-traversal.md`; CWE-434 for unrestricted upload.
- **Default severity:** high for unrestricted upload served from the app origin.

### SEC-ASVS-005 — Authentication and session (chapters V6, V7, V9, V10)

- **Look for:** weak credential rules, missing brute-force protection, session tokens with weak entropy, sessions that do not expire or rotate, JWT validation gaps, OAuth flows without state or PKCE.
- **Maps to:** `authn-session.md`.
- **Default severity:** high.

### SEC-ASVS-006 — Authorisation (chapter V8)

- **Look for:** access decisions made on the client; missing checks on object ownership; authorisation checks that are not enforced on every path to the same resource.
- **Maps to:** `owasp-api-top10.md` API1 and API5.
- **Default severity:** high to critical.

### SEC-ASVS-007 — API and web service (chapter V4)

- **Look for:** schema validation absent on request bodies; unsafe methods accepted on resources; GraphQL depth and complexity unbounded.
- **Maps to:** `owasp-api-top10.md`.
- **Default severity:** medium.

### SEC-ASVS-008 — Cryptography and secure communication (chapters V11, V12)

- **Look for:** weak algorithms, hard-coded keys, missing TLS verification, outdated TLS versions.
- **Maps to:** `crypto.md`.
- **Default severity:** high.

### SEC-ASVS-009 — Configuration (chapter V13)

- **Look for:** secrets in configuration files; debug settings; default accounts; unnecessary features; missing dependency controls.
- **Maps to:** `secrets-logging.md`, `docker-k8s-hardening.md`, `supply-chain-ssdf-slsa.md`.
- **Default severity:** medium to high.

### SEC-ASVS-010 — Data protection (chapter V14)

- **Look for:** sensitive data stored, cached, or transmitted without need; personal data in logs; missing data minimisation in responses.
- **Maps to:** `secrets-logging.md`, `owasp-api-top10.md` API3.
- **Default severity:** medium to high.

### SEC-ASVS-011 — Secure coding and architecture (chapter V15)

- **Look for:** dangerous functions used without a check; unsafe deserialisation; missing secure defaults in changed components; trust boundaries not documented.
- **Maps to:** `deserialisation.md`, `node-react.md`, `java.md`.
- **Default severity:** medium to high.

### SEC-ASVS-012 — Error handling and logging (chapter V16)

- **Look for:** detailed error output to users; security events not logged; logs with sensitive data; logs without integrity protection where required by level.
- **Maps to:** `secrets-logging.md`; OWASP A09 and A10.
- **Default severity:** medium.

### SEC-ASVS-013 — Mapping findings to requirements

- **Look for:** nothing in code. This rule governs reporting.
- **Rule:** a finding that cites ASVS must give the chapter, the requirement id, and the level. If the id cannot be confirmed for the declared version, cite the chapter and state "requirement id not verified".
- **Default severity:** not applicable.

## How to apply in review

1. Pick the level from the data sensitivity (SEC-ASVS-001) and state it.
2. For each changed control, name the chapter and the failing requirement.
3. Prefer the specific topic file for evidence and examples.
4. Do not claim full ASVS coverage from a diff review.
5. Mark ASVS-based findings with the edition caveat when the requirement number is not confirmed.
