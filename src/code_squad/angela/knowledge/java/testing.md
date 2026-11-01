---
title: Testing Java code
source: JUnit 5 User Guide; Mockito documentation (best practices, strict stubs); Testcontainers for Java documentation; AssertJ documentation
version: JUnit Jupiter 5.x; Mockito 5.x; Testcontainers 1.x or 2.x (verify in build file); Java 17+ baseline
reviewed: 2026-10
unverified-edition: true
---

## Scope

Unit, integration, and slice tests in Java: JUnit 5 structure, Mockito usage, Testcontainers for real dependencies, determinism, and test quality. Applies to changes in `src/test` and to changes that remove or weaken tests.

## Rules

### JAVA-TEST-001 — Tests assert behaviour

- **Look for:** tests without assertions; tests that only call code; `assertTrue(true)`; assertions on mocks that were set up in the same test (tautology); catching exceptions to make tests pass.
- **Why it matters:** the suite passes without checking anything.
- **Evidence:** the test method and the absence of an assertion that could fail.
- **Default severity:** medium.

### JAVA-TEST-002 — Mockito is used for collaborators, not for value objects

- **Look for:** mocks of records, DTOs, or simple value types; `mock()` for classes that are easy to construct; `verify` calls that check internal call sequences instead of outcomes.
- **Why it matters:** tests become coupled to implementation.
- **Default severity:** low.

### JAVA-TEST-003 — Mockito misuse

- **Look for:** mocking `final` classes without the inline mock maker when the project does not use it; `when(...).thenReturn` on methods the code under test never calls (strict stubs fail at runtime); `any()` matchers mixed with raw values; `@Spy` used to hide real calls; static mocks (`mockStatic`) that are not closed.
- **Why it matters:** false passes and unstable tests. Static mocks leak across tests if not closed.
- **Good:** `try (MockedStatic<Clock> m = mockStatic(...)) { ... }` or inject the dependency.
- **Default severity:** medium.

### JAVA-TEST-004 — Integration tests use real dependencies where it matters

- **Look for:** repository or persistence behaviour tested only with mocks; database queries never executed in tests; H2 used where the production database has different SQL dialect behaviour, with no note.
- **Why it matters:** SQL and migration issues appear only on the production engine.
- **Good:** Testcontainers with the same database version as production.
- **Default severity:** medium to high for query changes and migrations.

### JAVA-TEST-005 — Determinism

- **Look for:** `Thread.sleep` for synchronisation; `LocalDate.now()` or `Instant.now()` without an injected clock; random data without a seed; order-dependent tests sharing static state; real network calls to external services.
- **Why it matters:** flaky builds that teams stop trusting.
- **Good:** inject `Clock`; use `Awaitility` or latches for asynchronous outcomes.
- **Default severity:** medium.

### JAVA-TEST-006 — Test isolation and shared state

- **Look for:** static fields written in tests; `@SpringBootTest` contexts that modify shared beans without `@DirtiesContext` or cleanup; database rows left between tests.
- **Default severity:** medium.

### JAVA-TEST-007 — Exceptions are tested precisely

- **Look for:** `@Test` with `expected` (JUnit 4 style) in JUnit 5 projects; `try { ... fail(); } catch (Exception e) {}` patterns; `assertThrows(Exception.class, ...)` where a specific type is intended.
- **Good:** `assertThrows(NotFoundException.class, () -> service.find(id))` with a message assertion where the message is part of the contract.
- **Default severity:** low.

### JAVA-TEST-008 — Parameterised tests for input variation

- **Look for:** many near-identical test methods differing only by input; loops inside tests that stop at the first failure.
- **Good:** `@ParameterizedTest` with `@CsvSource` or `@MethodSource`.
- **Default severity:** low.

### JAVA-TEST-009 — Removed or disabled tests

- **Look for:** `@Disabled` without an issue reference; `@Test` commented out; assertions relaxed in an existing test during a change; `@Tag` changes that exclude tests from CI.
- **Why it matters:** coverage silently decreases.
- **Default severity:** medium.

### JAVA-TEST-010 — Test data does not contain real secrets or personal data

- **Look for:** real-looking tokens, passwords, emails, or card numbers in test fixtures; production dumps committed as test resources.
- **Default severity:** medium. Report location only.

### JAVA-TEST-011 — Testing async and reactive code

- **Look for:** tests that call `CompletableFuture.get()` without a timeout; reactive streams tested without `StepVerifier` or equivalent; `Thread.sleep` in place of waiting.
- **Default severity:** medium.

## How to apply in review

1. Check whether the change added, removed, or weakened tests.
2. For each new test, name a plausible mutation of the code that it would catch.
3. Check that integration tests for persistence use the production engine.
4. Verify the test framework from the build file (JUnit 5 versus JUnit 4 imports).
5. Cite the test class and method, and the production code it does or does not cover.
