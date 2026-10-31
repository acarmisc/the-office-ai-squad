---
title: API compatibility and logging
source: Semantic Versioning 2.0.0; Java Language Specification (binary compatibility, JLS 13); Jakarta EE namespace migration guidance; SLF4J manual; OWASP Logging Cheat Sheet
version: Java 21 LTS and Java 25 LTS; SLF4J 2.x; Jakarta EE 9+ namespace
reviewed: 2026-10
---

## Scope

Compatibility of public Java APIs (libraries and service contracts), the Jakarta namespace, and logging practice (levels, structure, sensitive data). Applies to public types, REST and messaging contracts consumed by others, and log statements in changed code.

## Rules

### JAVA-API-001 — Public API changes are compatible or versioned

- **Look for:** removed or renamed public methods, types, or fields; changed method signatures or return types; new abstract methods added to interfaces that clients implement; changed checked exceptions; enum constants removed.
- **Why it matters:** binary and source incompatibility breaks callers at compile or link time.
- **Evidence:** the old and new signatures, and the consumers in the repository or published artifact.
- **Good:** add an overload, deprecate with `@Deprecated(since = "...", forRemoval = true)`, and remove in a major version.
- **Default severity:** high for published libraries; medium for internal modules with multiple consumers.

### JAVA-API-002 — Default methods and interface evolution

- **Look for:** new abstract methods on interfaces that third parties implement; default methods added that conflict with existing implementations' methods of the same name.
- **Default severity:** high for published interfaces.

### JAVA-API-003 — Serialisation compatibility

- **Look for:** `Serializable` classes without `serialVersionUID`; field changes in serialised classes without compatibility planning; Java serialisation used for network or persisted data (see `SEC-DESER-*`).
- **Why it matters:** deserialisation fails or silently changes state. Java serialisation on untrusted input is a security risk.
- **Default severity:** medium; high when untrusted input is deserialised.

### JAVA-API-004 — REST contract changes

- **Look for:** removed or renamed JSON fields; changed types (`int` to `string`); changed enum values; required request fields added; status codes changed for existing error cases; pagination response shape changed.
- **Why it matters:** clients break at runtime without compile errors.
- **Evidence:** the DTO diff and the published OpenAPI or contract file if present.
- **Good:** additive changes; version the path or media type for breaking changes.
- **Default severity:** high for externally consumed APIs; medium for internal ones.

### JAVA-API-005 — Jakarta namespace

- **Look for:** `javax.persistence`, `javax.validation`, `javax.servlet`, `javax.annotation` imports in code built on Spring Boot 3, Jakarta EE 9+, or Hibernate 6 where `jakarta.*` is required.
- **Why it matters:** the code does not compile or the annotations are ignored at runtime.
- **Evidence:** the import and the framework major version.
- **Default severity:** high (compile or silent failure).

### JAVA-API-006 — Exceptions as part of the contract

- **Look for:** public methods that now throw unchecked exceptions for conditions previously returned as values; changed exception types that callers catch.
- **Default severity:** medium.

### JAVA-API-007 — Documentation of public behaviour

- **Look for:** public methods with changed nullability, thread-safety, or ordering guarantees without Javadoc update; `@Deprecated` without replacement guidance.
- **Default severity:** low.

### JAVA-LOG-001 — Use a logging facade with parameters

- **Look for:** `System.out.println` or `printStackTrace` in application code; string concatenation in log calls (`log.debug("x=" + x)`) where the level may be disabled; `String.format` before the logger call.
- **Good:** `log.debug("order {} status {}", orderId, status);`
- **Why it matters:** output goes to the wrong place, and disabled levels still pay the cost of building messages.
- **Default severity:** low to medium.

### JAVA-LOG-002 — Levels match meaning

- **Look for:** `ERROR` for expected validation failures; `INFO` for every request in hot paths; `WARN` for conditions the operator must act on, absent from important failure paths; `DEBUG` containing payloads.
- **Default severity:** low.

### JAVA-LOG-003 — No secrets or personal data in logs

- **Look for:** passwords, tokens, API keys, session ids, full request or response bodies, card numbers, national ids, email addresses in logs; `toString()` of sensitive objects in log calls.
- **Why it matters:** CWE-532 (insertion of sensitive information into log file). Logs are copied to many systems.
- **Evidence:** the log statement and the variable with sensitive content. Report the location only; never repeat the secret value.
- **Default severity:** high.

### JAVA-LOG-004 — Exceptions are logged once, with context

- **Look for:** the same exception logged at every layer (duplicate noise); exceptions logged without the stack trace (`log.error(e.getMessage())`); errors logged at the top of a request path and rethrown.
- **Good:** log once at the boundary where the failure is handled, with `log.error("...", id, e)`.
- **Default severity:** low.

### JAVA-LOG-005 — Log injection

- **Look for:** user-controlled strings written to logs without neutralising line breaks or control characters where logs are parsed line by line.
- **Why it matters:** forged log entries (CWE-117).
- **Default severity:** low to medium.

### JAVA-LOG-006 — Structured logging and correlation

- **Look for:** logs without request or trace identifiers where the service uses tracing; ad hoc JSON built by string concatenation.
- **Good:** use the project's MDC or structured-logging API.
- **Default severity:** low.

## How to apply in review

1. For public types, compare old and new signatures explicitly, listing each change.
2. For REST contracts, compare the DTO and the contract file.
3. For each new log statement, check the variables for sensitive data.
4. Cite the file, line, and the change that breaks compatibility or exposes data.
5. Record the framework namespace (`javax` or `jakarta`) before flagging imports.
