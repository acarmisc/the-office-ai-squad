---
title: Resource handling and exceptions
source: Oracle Java SE 21 documentation (try-with-resources, Exceptions tutorial); Effective Java 3rd edition, Items 69-77; JEP 358 (Helpful NullPointerExceptions)
version: Java 21 LTS; Java 25 LTS (current)
reviewed: 2026-10
---

## Scope

Closing resources (streams, connections, files, sockets, executors), exception design, catching and rethrowing, and transaction-related exception behaviour. Applies to all Java code. Framework-specific transaction rules are in `spring-core`.

## Rules

### JAVA-RES-001 — Use try-with-resources for every AutoCloseable

- **Look for:** `InputStream`, `OutputStream`, `Reader`, `Writer`, `Connection`, `Statement`, `ResultSet`, `Socket`, `ExecutorService` (Java 19+ implements `AutoCloseable`), and `Stream` from `Files.lines` opened without `try-with-resources` or a `finally` that closes them.
- **Why it matters:** file descriptor and connection leaks appear under load, not in tests.
- **Evidence:** the open call and the absence of a close on every path, including exceptions.
- **Bad:** `BufferedReader r = Files.newBufferedReader(p); ... r.close();` with no `finally`.
- **Good:** `try (var r = Files.newBufferedReader(p)) { ... }`
- **Default severity:** high.

### JAVA-RES-002 — Close order and suppressed exceptions

- **Look for:** manual `close()` calls in `finally` that throw and hide the original exception; multiple resources closed by hand in the wrong order.
- **Why it matters:** try-with-resources closes in reverse order and records close failures as suppressed exceptions.
- **Default severity:** medium.

### JAVA-RES-003 — Do not swallow exceptions

- **Look for:** empty `catch` blocks; `catch (Exception e) { }`; `catch` that logs at debug level and continues with a default value; `catch (Throwable t)` without rethrow.
- **Why it matters:** failures become silent data corruption or incorrect results.
- **Evidence:** the catch block and the state the code continues with.
- **Default severity:** high in business logic; medium in cleanup-only code where a comment justifies it.

### JAVA-RES-004 — Catch the narrowest type

- **Look for:** `catch (Exception e)` or `catch (RuntimeException e)` around multi-step code where unrelated failures are then mistaken for the expected case.
- **Default severity:** medium.

### JAVA-RES-005 — Preserve the cause

- **Look for:** `throw new XException(e.getMessage())` without the original exception; wrapping in a generic `RuntimeException` that loses the type; logging and rethrowing the same exception at each layer (duplicate log entries).
- **Good:** `throw new OrderException("payment failed for order " + id, e);`
- **Default severity:** medium.

### JAVA-RES-006 — Exception types carry meaning

- **Look for:** `RuntimeException` thrown for expected business conditions (not found, conflict, invalid state); checked exceptions wrapped in unchecked ones at every layer without a boundary; `IllegalStateException` used for input validation.
- **Why it matters:** callers and the HTTP layer cannot map failures to responses.
- **Default severity:** low to medium.

### JAVA-RES-007 — Do not use exceptions for control flow

- **Look for:** `try { parse() } catch (NumberFormatException) { ... }` used in normal loops; exceptions thrown to exit iteration.
- **Default severity:** low.

### JAVA-RES-008 — Finally blocks do not discard results

- **Look for:** `return` inside `finally`; exceptions thrown from `finally` replacing the original.
- **Default severity:** high.

### JAVA-RES-009 — Errors are not caught

- **Look for:** `catch (Error e)` or `catch (OutOfMemoryError e)` in application code; `catch (Throwable t)` that does not rethrow `InterruptedException` handling correctly (see JAVA-CONC-004).
- **Default severity:** medium.

### JAVA-RES-010 — Checked exception handling at the right layer

- **Look for:** `throws Exception` on public methods that hide the actual failure types; checked exceptions declared on lambdas by wrapping in generic `RuntimeException` without context.
- **Default severity:** low.

### JAVA-RES-011 — Stack traces are not used as user output

- **Look for:** `e.printStackTrace()` in application code (use the logger); stack traces returned in HTTP responses.
- **Why it matters:** log format and information disclosure (see `api-compat-logging`).
- **Default severity:** medium.

## How to apply in review

1. Search the diff for `new` of closeable types and check each for try-with-resources.
2. Read every catch block in changed code and state what happens to the failure.
3. Check the exception type against the caller's ability to act on it.
4. Cite the file, line, and the path on which the resource or failure escapes.
5. Do not flag `catch` blocks that are documented, narrow, and deliberately ignore a known condition.
