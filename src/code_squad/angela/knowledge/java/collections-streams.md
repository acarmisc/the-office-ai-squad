---
title: Collections and streams
source: Oracle Java SE 21 API documentation (java.util collections, java.util.stream, SequencedCollection JEP 431); Effective Java 3rd edition, Items 45-47; JEP 485 (Stream Gatherers, final in JDK 24)
version: Java 21 LTS; Java 25 LTS (current)
reviewed: 2026-10
---

## Scope

Choice and use of collections, iteration, mutation during iteration, streams, and collectors. Applies to application code and library code on Java 8 and later. Feature availability is noted per rule.

## Rules

### JAVA-COLL-001 — Choose the collection for the access pattern

- **Look for:** `List.contains` in a loop over large data (O(n) per check); `LinkedList` used for random access; `HashMap` where iteration order is relied on; `TreeMap` used without ordering need.
- **Why it matters:** quadratic time on realistic input sizes.
- **Evidence:** the input size source and the operation count.
- **Good:** `Set<String> ids = new HashSet<>(list);` before the loop.
- **Default severity:** medium when input is unbounded or user-controlled; low otherwise.

### JAVA-COLL-002 — Do not modify a collection while iterating it

- **Look for:** `list.remove` or `map.put` inside a for-each loop over the same collection; `Iterator` usage without `iterator.remove()`.
- **Why it matters:** `ConcurrentModificationException` or skipped elements.
- **Good:** `list.removeIf(predicate)` or `iterator.remove()`.
- **Default severity:** high.

### JAVA-COLL-003 — Immutable collections for shared state

- **Look for:** `Collections.unmodifiableList(list)` returned while the backing list is still mutated elsewhere; `Arrays.asList` returned as if it were fully mutable (fixed size); `List.of` used where nulls can appear (throws).
- **Default severity:** medium.

### JAVA-COLL-004 — Map computations use the atomic methods

- **Look for:** `map.get(k)` followed by `map.put(k, ...)` for accumulation; `getOrDefault` followed by `put`; `merge` available but not used.
- **Good:** `counts.merge(key, 1, Integer::sum);` and `map.computeIfAbsent(key, k -> new ArrayList<>()).add(v);`
- **Default severity:** low (medium on concurrent maps; see `concurrency` JAVA-CONC-002).

### JAVA-COLL-005 — Streams are for transformation, not side effects

- **Look for:** `forEach` or `peek` that mutates external state; `collect` into a shared list from a parallel stream; streams reused after a terminal operation (throws `IllegalStateException`).
- **Why it matters:** side effects in streams are unordered in parallel and hard to follow.
- **Bad:** `list.stream().forEach(x -> results.add(f(x)));`
- **Good:** `List<R> results = list.stream().map(this::f).toList();`
- **Default severity:** medium.

### JAVA-COLL-006 — Do not use parallel streams by default

- **Look for:** `parallelStream()` on small collections, on I/O work, on collections whose elements share state, or inside code that already runs on a thread pool.
- **Why it matters:** the common fork-join pool is shared by the whole JVM. Overhead often exceeds gain.
- **Evidence:** the size, the operation, and a benchmark if one exists.
- **Default severity:** medium.

### JAVA-COLL-007 — Collectors: right type and null behaviour

- **Look for:** `Collectors.toMap` without a merge function (throws on duplicate keys); `Collectors.toMap` with null values (throws); `Collectors.groupingBy` into `HashMap` when order matters.
- **Good:** `toMap(k, v, (a, b) -> a, LinkedHashMap::new)` when duplicates are possible and order matters.
- **Default severity:** medium.

### JAVA-COLL-008 — Stream.toList versus collect

- **Look for:** `collect(Collectors.toList())` where `stream().toList()` (Java 16+) gives an unmodifiable list and is sufficient; the reverse, where the caller later mutates the result.
- **Why it matters:** `toList()` returns an unmodifiable list. Callers that add elements fail at runtime.
- **Requires:** Java 16 or later for `Stream.toList()`.
- **Default severity:** low.

### JAVA-COLL-009 — Lazy streams are not left open

- **Look for:** `Files.lines`, `Files.walk`, `Stream` from I/O APIs not closed; streams returned from methods without a documented close responsibility.
- **Why it matters:** file handle leaks. See `resources-exceptions` JAVA-RES-001.
- **Default severity:** high.

### JAVA-COLL-010 — Readability over clever chains

- **Look for:** stream pipelines of more than about four operations with nested lambdas and ternaries; a loop written as a stream where a simple `for` is clearer.
- **Default severity:** low. Do not flag consistent team style.

### JAVA-COLL-011 — Sequenced collections for ends and reversal

- **Look for:** `list.get(list.size() - 1)` or manual reversal where `getLast()`, `getFirst()`, or `reversed()` exist.
- **Requires:** Java 21 (SequencedCollection, JEP 431).
- **Default severity:** low.

### JAVA-COLL-012 — Gatherers are for stateful intermediate steps

- **Look for:** hand-written stateful stream logic (windowing, scan) that a `Gatherer` would express more clearly.
- **Requires:** Java 24 (final). Preview in 22 and 23.
- **Default severity:** low (advisory only).

### JAVA-COLL-013 — Arrays and primitives

- **Look for:** boxed `Integer` or `Long` in large collections where a primitive stream (`IntStream`, `LongStream`) or array fits; `Arrays.asList(array)` on primitive arrays (yields `List<int[]>`).
- **Default severity:** low.

### JAVA-COLL-014 — Hash keys are not mutated

- **Look for:** mutable objects used as `HashMap` or `HashSet` keys with fields that participate in `hashCode`.
- **Why it matters:** the element becomes unreachable. See `immutability-equality` JAVA-IMM-005.
- **Default severity:** high.

## How to apply in review

1. Look for loops over input collections that call `contains` or `indexOf` on another list.
2. Check for mutation of the iterated collection.
3. Check stream terminal operations for side effects and for unclosed I/O streams.
4. Confirm the Java release before suggesting `toList()`, sequenced methods, or gatherers.
5. Cite the expression and the input size.
