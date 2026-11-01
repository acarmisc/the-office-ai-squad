---
title: Performance pitfalls in Java
source: Oracle Java SE 21 documentation (java.util, java.time, String); Effective Java 3rd edition (Items 58-61 on performance); OpenJDK JMH documentation; Java Performance (Scott Oaks, 2nd edition)
version: Java 21 LTS; Java 25 LTS (current)
reviewed: 2026-10
---

## Scope

Common performance problems in Java code review: allocation and boxing, string building, regular expressions, I/O buffering, serialisation costs, repeated expensive setup, and unbounded growth. Performance claims require evidence: a benchmark, a profile, a measured latency, or a clearly stated input size. Do not report speculative micro-optimisation.

## Rules

### JAVA-PERF-001 — Evidence before optimisation

- **Look for:** rewrites justified as performance work with no measurement and no hot path identified.
- **Why it matters:** the change adds risk without measurable gain.
- **Evidence to request:** JMH result, profiler sample, production metric, or input-size estimate.
- **Default severity:** low (advisory). Raise only when the change also hurts readability in a hot path with a measured regression.

### JAVA-PERF-002 — Unbounded growth

- **Look for:** caches (`HashMap`, `ConcurrentHashMap`, Guava or Caffeine without bounds) keyed by user input; lists that accumulate across requests; static collections never cleared; event listeners added and not removed.
- **Why it matters:** memory grows until the process is restarted.
- **Good:** bounded caches with eviction (Caffeine `maximumSize` or `expireAfterWrite`), or a size limit.
- **Default severity:** high when keyed by user input; medium otherwise.

### JAVA-PERF-003 — Boxing in hot loops

- **Look for:** `Integer`, `Long`, or `Double` accumulation inside loops over large ranges; `Map<Integer, ...>` where primitive specialisations or arrays fit; autoboxing in `stream().mapToInt` misuse.
- **Default severity:** low (medium in measured hot paths).

### JAVA-PERF-004 — String building

- **Look for:** `+=` concatenation of strings inside loops; `StringBuilder` created per element; `String.format` in tight loops; `String.join` or `Collectors.joining` used where a builder is clearer.
- **Why it matters:** quadratic copying in loops. Modern compilers optimise simple concatenation, not loop accumulation.
- **Good:** one `StringBuilder` outside the loop.
- **Default severity:** low to medium on large inputs.

### JAVA-PERF-005 — Regular expressions compiled once

- **Look for:** `String.matches`, `replaceAll`, or `split` with a pattern inside a loop or request path (each call compiles the pattern); `Pattern.compile` inside methods called per request.
- **Good:** `private static final Pattern P = Pattern.compile("...");`
- **Also check:** catastrophic backtracking on user input (ReDoS, CWE-1333). Route to `dwight`.
- **Default severity:** low to medium; high for ReDoS on untrusted input.

### JAVA-PERF-006 — Buffered I/O

- **Look for:** `FileInputStream` or `FileOutputStream` read byte by byte or in small chunks without buffering; `System.out` writes in loops without a buffer; `Files.readAllBytes` on large or unbounded files.
- **Why it matters:** system calls per byte. Memory exhaustion on large files.
- **Default severity:** medium.

### JAVA-PERF-007 — Repeated expensive setup

- **Look for:** `ObjectMapper`, `DocumentBuilderFactory`, `SecureRandom`, `HttpClient`, `DateTimeFormatter`, or JDBC `DataSource` created per call; `Gson` or `Jackson` schema construction in request paths.
- **Why it matters:** these objects are thread-safe to share and expensive to create.
- **Good:** create once as a singleton bean or static final field, after confirming thread safety in the library's documentation.
- **Default severity:** medium.

### JAVA-PERF-008 — N+1 at the I/O layer

- **Look for:** HTTP calls, cache lookups, or database queries inside a loop over a collection; per-item calls to a service that supports batch requests.
- **Why it matters:** latency multiplies with input size. See also `jpa-persistence` JAVA-JPA-001.
- **Good:** batch endpoints, `IN` queries, or parallel calls with a bounded executor.
- **Default severity:** high on request paths with unbounded input.

### JAVA-PERF-009 — Logging cost

- **Look for:** log statements that build expensive messages at disabled levels (`log.debug("x" + toJson(big))`); logging of full payloads in hot loops.
- **Good:** parameterised logging; `log.isDebugEnabled()` guard around expensive argument computation.
- **Default severity:** low to medium.

### JAVA-PERF-010 — Exceptions in hot paths

- **Look for:** exceptions created and thrown for normal control flow in loops; fill-in stack traces on frequently thrown exceptions where the trace is not needed.
- **Good:** `return Optional.empty()` for expected absence; override `fillInStackTrace` only for hot, internal control-flow exceptions with a comment.
- **Default severity:** low.

### JAVA-PERF-011 — Lock contention and synchronised hot paths

- **Look for:** `synchronized` on a global object in a request path; a single lock guarding unrelated data.
- **Why it matters:** serialises throughput. See `concurrency`.
- **Default severity:** medium with evidence.

### JAVA-PERF-012 — Serialisation of large objects

- **Look for:** whole entity graphs serialised to JSON for responses; large objects copied to build small responses; `Object.clone` or copy constructors in loops.
- **Default severity:** low to medium.

### JAVA-PERF-013 — Virtual thread and pool sizing

- **Look for:** fixed pools sized at arbitrary numbers without reference to the downstream capacity; virtual threads used to replace bounded resources such as database connections (they do not increase connection capacity).
- **Why it matters:** the bottleneck moves to the pool and produces timeouts.
- **Default severity:** medium.

## How to apply in review

1. Identify whether the code is on a request path, a batch path, or a startup path, and state it.
2. Estimate the input size from the data source. If unknown, lower confidence.
3. Prefer findings with unbounded growth, N+1, and repeated setup over micro-optimisations.
4. Ask for a benchmark for any claimed speed-up, and do not accept claims made in comments alone.
5. Cite the code path, input size, and the expected cost in the finding.
