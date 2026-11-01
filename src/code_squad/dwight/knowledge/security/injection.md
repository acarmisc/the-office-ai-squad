---
title: Injection (SQL, NoSQL, OS command, LDAP, template, expression language)
source: OWASP Injection Prevention Cheat Sheet; OWASP SQL Injection Prevention Cheat Sheet; OWASP OS Command Injection Defense Cheat Sheet; OWASP Testing Guide
version: OWASP Top 10:2025 A05 (current cheat sheets as of review date)
reviewed: 2026-10
---

## Scope

Interpreters that receive untrusted input as part of a command or query: relational SQL, document database queries, operating system shells, LDAP filters, XPath, template engines, and expression languages. The rules here are general. Language-specific forms are in `node-react.md` and `java.md`.

## Rules

### SEC-INJECT-001 — SQL built by string concatenation

- **Look for:** `"SELECT ... WHERE id = " + id`, template literals with interpolated input in SQL, `String.format` building queries, ORM raw query methods receiving concatenated strings.
- **Why it matters:** attacker-controlled SQL executes with the application's database privileges. CWE-89 is rank 2 in the CWE Top 25 (2025).
- **Evidence:** the query construction line, the input source, and whether the input reaches the query without parameter binding.
- **Bad:** `db.query("SELECT * FROM users WHERE email = '" + email + "'")`
- **Good:** `db.query("SELECT * FROM users WHERE email = ?", [email])`
- **Default severity:** critical if the endpoint is unauthenticated; high otherwise.

### SEC-INJECT-002 — Dynamic identifiers and ORDER BY

- **Look for:** table names, column names, sort fields, or sort direction taken from request parameters and inserted into SQL. Parameter binding does not apply to identifiers.
- **Good:** map the input through an allowlist (`{ name: 'created_at', score: 'score' }`), reject anything else.
- **Default severity:** high.

### SEC-INJECT-003 — LIKE patterns and wildcard handling

- **Look for:** user input inserted into `LIKE` patterns without escaping `%` and `_`; this allows broad matches and can cause expensive queries.
- **Default severity:** low to medium.

### SEC-INJECT-004 — NoSQL operator injection

- **Look for:** request bodies passed directly to document queries, so that an object such as `{"$ne": null}` replaces a scalar value; `$where` or server-side JavaScript evaluation with input; `find(req.body)`.
- **Good:** validate the type of each field (string, not object) before building the query.
- **Default severity:** high to critical for authentication queries.
- **CWE:** CWE-943.

### SEC-INJECT-005 — OS command injection

- **Look for:** `exec`, `execSync`, `spawn` with `shell: true`, `system()`, `Runtime.getRuntime().exec(String)`, `ProcessBuilder` with `sh -c` and concatenated input, shell wrappers around CLI tools.
- **Why it matters:** CWE-78 is rank 9 in the CWE Top 25 (2025). Command execution gives the attacker the host.
- **Good:** call the executable with an argument array and no shell (`execFile`, `ProcessBuilder` with separate arguments); validate arguments against an allowlist; never pass input as a flag name without validation (for example `--output=` with a user path, or option injection with a leading `-`).
- **Default severity:** critical when reachable; high otherwise.

### SEC-INJECT-006 — Argument (option) injection

- **Look for:** input passed as a positional argument that the called tool interprets as an option, such as a value beginning with `-`, even when no shell is used. Also `git`, `tar`, `curl`, and `rsync` options accepting file paths or URLs.
- **Good:** place `--` before user-controlled positional arguments where the tool supports it; validate that values do not start with `-`.
- **Default severity:** high.

### SEC-INJECT-007 — LDAP injection

- **Look for:** LDAP filters built with concatenated user input; distinguished names built from input without escaping.
- **Good:** escape filter and DN values with the library's encoder, or use parameterised search APIs.
- **Default severity:** high.
- **CWE:** CWE-90.

### SEC-INJECT-008 — XPath injection

- **Look for:** XPath expressions built from input.
- **Good:** use XPath variables.
- **Default severity:** medium to high.
- **CWE:** CWE-643.

### SEC-INJECT-009 — Server-side template injection

- **Look for:** user input used as template source rather than data (for example, building a template string from input and rendering it); template engines configured to allow arbitrary expressions.
- **Good:** pass input as data to a fixed template; sandbox engines that must accept user templates, and prefer not to.
- **Default severity:** critical when template evaluation is reachable.
- **CWE:** CWE-1336, CWE-94.

### SEC-INJECT-010 — Expression language injection

- **Look for:** SpEL, OGNL, MVEL, JEXL, or similar evaluated over input. See `java.md`.
- **Default severity:** critical when reachable.
- **CWE:** CWE-917.

### SEC-INJECT-011 — Stored procedures are not a fix by themselves

- **Look for:** stored procedures or functions that build dynamic SQL from parameters with `EXECUTE` or concatenation inside the database.
- **Default severity:** high.

### SEC-INJECT-012 — Escaping is not a substitute for parameters

- **Look for:** hand-written escape functions (`replace("'", "''")`) used instead of parameter binding; escaping that does not cover the context (for example, backslashes or multibyte encodings).
- **Good:** use parameter binding. Use escaping only where the interface offers no other option, and then use the library's function.
- **Default severity:** medium to high.

## How to apply in review

1. Find every place where a string is passed to an interpreter (`query`, `exec`, `filter`, `render`, `eval`).
2. Trace the input back to a request, message, or file. Confirm whether it is untrusted.
3. Check whether the input is bound as a parameter or an argument, or concatenated.
4. For identifiers and options, check for an allowlist.
5. Cite the sink line, the source, and the exploit input class (for example, a quote character, an operator object, or a leading dash). Do not include working payloads in the report.
