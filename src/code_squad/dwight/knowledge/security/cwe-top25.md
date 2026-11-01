---
title: CWE Top 25 Most Dangerous Software Weaknesses (2025) for review
source: MITRE and CISA, 2025 CWE Top 25 Most Dangerous Software Weaknesses (cwe.mitre.org/top25)
version: 2025 CWE Top 25 (page updated 15 December 2025)
reviewed: 2026-10
---

## Scope

The 2025 ranking of CWE weaknesses, with the review cue for each. Use it to prioritise findings: when several weaknesses are possible in a diff, report the one that appears in this list first, and always cite the most specific CWE. The ranking is a prioritisation aid, not a severity rating. Severity still comes from exploitability and impact in the change under review.

## Rules

Rank and CWE id are from the 2025 list. Score is the list's published weighting and is shown for orientation only.

### SEC-CWE-001 — CWE-79 Cross-site Scripting (rank 1)

- **Review cue:** untrusted data rendered into HTML, attributes, scripts, or URLs without context-correct encoding. See `xss-csrf.md`.
- **Default severity:** high.

### SEC-CWE-002 — CWE-89 SQL Injection (rank 2)

- **Review cue:** string-built SQL, dynamic `ORDER BY` or table names from input, unsafe ORM raw queries. See `injection.md`.
- **Default severity:** critical when reachable unauthenticated; high otherwise.

### SEC-CWE-003 — CWE-352 Cross-Site Request Forgery (rank 3)

- **Review cue:** state-changing endpoints accepting cookie-authenticated requests without a CSRF token or origin check; `GET` requests with side effects. See `xss-csrf.md`.
- **Default severity:** high.

### SEC-CWE-004 — CWE-862 Missing Authorization (rank 4)

- **Review cue:** a route or action that performs an operation with no authorisation check. See `owasp-api-top10.md` API1 and API5.
- **Default severity:** high to critical.

### SEC-CWE-005 — CWE-787 Out-of-bounds Write (rank 5)

- **Review cue:** native code, unsafe memory operations, or buffer handling with unchecked lengths. Usually outside the JS and Java focus; flag when present in the diff and route to the owning team.
- **Default severity:** high.

### SEC-CWE-006 — CWE-22 Path Traversal (rank 6)

- **Review cue:** file paths built from input without canonicalisation and containment checks. See `ssrf-path-traversal.md`.
- **Default severity:** high.

### SEC-CWE-007 — CWE-416 Use After Free (rank 7)

- **Review cue:** native code only. Out of scope for JS and Java diffs; route if present.
- **Default severity:** high.

### SEC-CWE-008 — CWE-125 Out-of-bounds Read (rank 8)

- **Review cue:** native code, parsers reading beyond buffers. Route if present.
- **Default severity:** medium to high.

### SEC-CWE-009 — CWE-78 OS Command Injection (rank 9)

- **Review cue:** shell invocation with input, `exec` with a shell string, `child_process` with `shell: true`, `Runtime.exec` with concatenated strings. See `injection.md`.
- **Default severity:** critical when reachable; high otherwise.

### SEC-CWE-010 — CWE-94 Code Injection (rank 10)

- **Review cue:** `eval`, dynamic code generation, template engines evaluating input, expression language evaluation of input. See `injection.md` and `node-react.md`.
- **Default severity:** critical when reachable; high otherwise.

### SEC-CWE-011 — CWE-120 Buffer Copy without Checking Size of Input (rank 11)

- **Review cue:** native code copy operations. Route if present.
- **Default severity:** high.

### SEC-CWE-012 — CWE-434 Unrestricted Upload of File with Dangerous Type (rank 12)

- **Review cue:** uploads accepted without type, extension, and content checks; uploads stored and served from the application origin; executable or template types accepted.
- **Default severity:** high.

### SEC-CWE-013 — CWE-476 NULL Pointer Dereference (rank 13)

- **Review cue:** unchecked nullable returns in native code or unchecked nulls in security decisions (a null principal treated as allowed). In Java and JS, flag when null feeds an authorisation or parsing decision.
- **Default severity:** medium; high in security decisions.

### SEC-CWE-014 — CWE-121 Stack-based Buffer Overflow (rank 14)

- **Review cue:** native code. Route if present.
- **Default severity:** high.

### SEC-CWE-015 — CWE-502 Deserialization of Untrusted Data (rank 15)

- **Review cue:** deserialising input from outside the trust boundary with default typing or unsafe loaders. See `deserialisation.md`.
- **Default severity:** critical when reachable; high otherwise.

### SEC-CWE-016 — CWE-122 Heap-based Buffer Overflow (rank 16)

- **Review cue:** native code. Route if present.
- **Default severity:** high.

### SEC-CWE-017 — CWE-863 Incorrect Authorization (rank 17)

- **Review cue:** an authorisation check exists but compares the wrong subject, object, or action. See `owasp-api-top10.md`.
- **Default severity:** high to critical.

### SEC-CWE-018 — CWE-20 Improper Input Validation (rank 18)

- **Review cue:** input accepted without type, range, length, or format checks at a boundary. Validation must be server-side for security decisions.
- **Default severity:** medium; high when the input drives a security-relevant sink.

### SEC-CWE-019 — CWE-284 Improper Access Control (rank 19)

- **Review cue:** general access control failure; cite the more specific CWE where possible (CWE-862, CWE-863, CWE-639).
- **Default severity:** high.

### SEC-CWE-020 — CWE-200 Exposure of Sensitive Information to an Unauthorized Actor (rank 20)

- **Review cue:** responses or logs containing data the caller should not see; verbose errors; debug endpoints. See `secrets-logging.md`.
- **Default severity:** medium; high for credentials or personal data.

### SEC-CWE-021 — CWE-306 Missing Authentication for Critical Function (rank 21)

- **Review cue:** an endpoint performing a critical action with no authentication. See `authn-session.md`.
- **Default severity:** critical.

### SEC-CWE-022 — CWE-918 Server-Side Request Forgery (rank 22)

- **Review cue:** server fetches a URL that the caller can influence. See `ssrf-path-traversal.md`.
- **Default severity:** high; critical when reaching metadata or internal admin services.

### SEC-CWE-023 — CWE-77 Command Injection (rank 23)

- **Review cue:** the general form of CWE-78; cite CWE-78 when the sink is a shell, CWE-77 for other command or tool constructions (for example an LLM-built command string).
- **Default severity:** critical when reachable; high otherwise.

### SEC-CWE-024 — CWE-639 Authorization Bypass Through User-Controlled Key (rank 24)

- **Review cue:** object identifier from the client used without an ownership check. See `owasp-api-top10.md` API1.
- **Default severity:** high.

### SEC-CWE-025 — CWE-770 Allocation of Resources Without Limits or Throttling (rank 25)

- **Review cue:** unbounded lists, uploads, retries, queues, or model calls. See `owasp-api-top10.md` API4 and `owasp-llm-top10.md` LLM10.
- **Default severity:** medium; high for unauthenticated endpoints.

## How to apply in review

1. List the weaknesses that the diff could introduce, then rank them by this list.
2. Report the most specific CWE that matches, and the rank only in the summary, not as a severity.
3. Where a weakness is native-code only and the diff is JS or Java, say so and route it.
4. Use the review cue to confirm the weakness is present before reporting.
5. Do not inflate severity because a CWE is ranked high. Severity depends on reachability and impact.
