---
title: Null safety and Optional
source: Oracle Java SE 21 API documentation (java.util.Optional, Objects); JSR 305 annotations status; JEP 358 (Helpful NullPointerExceptions); Spring Framework nullability annotations (JSpecify-aligned)
version: Java 21 LTS; Java 25 LTS (current)
reviewed: 2026-10
---

## Scope

Null handling in Java code: returning and accepting nulls, `Optional` use, `Objects` helpers, nullability annotations, and defensive checks at boundaries. Applies to application and library code on any supported Java release. Java has no null type checking in the language; these rules are about intent and review.

## Rules

### JAVA-NULL-001 — Do not return null for collections or arrays

- **Look for:** methods returning `null` where the type is `List`, `Set`, `Map`, or an array.
- **Why it matters:** callers must remember to check, and most do not. Empty values are a valid, safe default.
- **Evidence:** the method signature and a caller that dereferences the result without a check.
- **Bad:** `return user.getRoles() == null ? null : user.getRoles();`
- **Good:** `return roles == null ? List.of() : List.copyOf(roles);`
- **Default severity:** medium; high at a public API boundary.

### JAVA-NULL-002 — Optional is a return type, not a field or parameter

- **Look for:** `Optional` as a field, a method parameter, or in collections (`List<Optional<T>>`); `Optional` returned from getters that could return an empty collection.
- **Why it matters:** `Optional` is designed for return values. As fields it is not serialisable by default and adds allocation. As parameters it forces callers to wrap values.
- **Evidence:** the declaration and its usage.
- **Default severity:** low to medium.

### JAVA-NULL-003 — Do not call get() without a presence check

- **Look for:** `optional.get()` or `orElseThrow()` used without `isPresent()` or with a fallback that hides absence; `Optional.of(x)` where `x` may be null (throws).
- **Why it matters:** `NoSuchElementException` or `NullPointerException` at runtime with an unclear cause.
- **Good:** `repo.findById(id).orElseThrow(() -> new NotFoundException(id))`
- **Default severity:** medium.

### JAVA-NULL-004 — Optional chaining stays readable

- **Look for:** `map` and `flatMap` chains that call methods for side effects; `ifPresent` used where a plain `if` is clearer; `orElse(expensiveCall())` that evaluates the call eagerly.
- **Why it matters:** side effects in chains are hard to follow, and `orElse` always evaluates its argument.
- **Good:** `orElseGet(() -> expensiveCall())`
- **Default severity:** low.

### JAVA-NULL-005 — Parameters and returns are annotated where the project uses annotations

- **Look for:** public API methods without nullability information in a codebase that uses `@NonNull`/`@Nullable` (JSpecify, Spring `@NonNullApi`, Checker Framework, Jakarta, or Lombok); annotations that contradict the implementation.
- **Why it matters:** annotations document the contract and feed static analysis.
- **Evidence:** the annotation package in use and the mismatched method.
- **Default severity:** low to medium.

### JAVA-NULL-006 — Validate at boundaries, trust inside

- **Look for:** null checks repeated at every internal call; missing validation at controller, message listener, or public library entry points.
- **Why it matters:** boundaries receive untrusted input. Internal code can assume invariants established there.
- **Evidence:** the boundary method and the absent check.
- **Default severity:** medium.

### JAVA-NULL-007 — Use Objects helpers for clarity

- **Look for:** hand-written `a == null ? b : a` or `x != null && x.equals(y)` where `Objects.requireNonNullElse`, `Objects.equals`, or `Objects.requireNonNull(x, "message")` expresses the intent.
- **Default severity:** low.

### JAVA-NULL-008 — Null in maps and sets is a deliberate choice

- **Look for:** `Map.of`, `List.of`, `Set.of` receiving nulls (throw `NullPointerException`); `Map.get` returning null treated as missing without `containsKey` or `getOrDefault`; `ConcurrentHashMap` receiving null keys or values (throws).
- **Why it matters:** runtime exceptions in code paths that tests did not cover.
- **Default severity:** medium.

### JAVA-NULL-009 — Helpful NPE messages are not a substitute for checks

- **Look for:** code that relies on catching `NullPointerException` to handle absence.
- **Why it matters:** catching NPE hides programming errors and is slower than explicit checks.
- **Default severity:** medium.

## How to apply in review

1. Check public signatures first: return types, parameter types, and annotations.
2. For each `Optional`, check the usage pattern (`orElseThrow` with a message is preferred for required values).
3. For each null return, find the callers and state whether they dereference it.
4. Note the Java release from the build (see `build-hygiene`) before recommending language features.
5. Cite the method signature and the caller that fails.
