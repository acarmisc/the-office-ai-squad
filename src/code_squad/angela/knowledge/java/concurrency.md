---
title: Concurrency, virtual threads and locking
source: Oracle Java SE 21 documentation (java.util.concurrent, JEP 444 Virtual Threads); JEP 491 (Synchronize Virtual Threads without Pinning, JDK 24); JEP 506 (Scoped Values, final in JDK 25); Java Concurrency in Practice (Goetz et al.)
version: Java 21 LTS; Java 25 LTS (current)
reviewed: 2026-10
---

## Scope

Shared mutable state, thread safety, `ExecutorService`, `CompletableFuture`, locks, interruption, virtual threads, and `ThreadLocal`. Applies to all Java code that runs on more than one thread, including servlet and async framework threads.

## Rules

### JAVA-CONC-001 — Shared mutable state is guarded or confined

- **Look for:** instance fields written by request or worker threads without synchronisation; non-thread-safe collections (`ArrayList`, `HashMap`, `SimpleDateFormat`, `DecimalFormat`) in shared fields; singletons with mutable state.
- **Why it matters:** data races produce wrong results that are hard to reproduce.
- **Evidence:** the field, the threads that write it, and the absence of a lock or thread-safe type.
- **Good:** `ConcurrentHashMap`, `AtomicLong`, `java.time` formatters (immutable and thread-safe), or confinement to one thread.
- **Default severity:** high.

### JAVA-CONC-002 — Check-then-act is atomic

- **Look for:** `if (!map.containsKey(k)) map.put(k, v)` on a concurrent map; `if (count < max) count++` on a shared counter.
- **Why it matters:** another thread acts between the check and the write.
- **Good:** `map.computeIfAbsent(k, ...)`, `AtomicInteger.updateAndGet`.
- **Default severity:** high.

### JAVA-CONC-003 — Lock scope and ordering

- **Look for:** locks held across remote calls, database calls, or sleeps; locks acquired in inconsistent order across methods; `synchronized` on publicly visible objects (`this`, class literals, strings, boxed values).
- **Why it matters:** deadlock, starvation, and throughput collapse.
- **Evidence:** the lock, the blocking call inside it, and the second lock acquisition order.
- **Default severity:** high.

### JAVA-CONC-004 — Interruption is preserved

- **Look for:** `catch (InterruptedException e) { }` or `catch (InterruptedException e) { log }` that does not restore the flag; loops that ignore interruption.
- **Good:** `catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new CancellationException(...); }` or propagate the exception.
- **Why it matters:** cancellation and shutdown do not work.
- **Default severity:** high.

### JAVA-CONC-005 — Executors are owned and shut down

- **Look for:** `Executors.newFixedThreadPool` (and similar) created per request; executors never shut down; unbounded queues (`Executors.newFixedThreadPool` uses an unbounded queue; `newCachedThreadPool` has unbounded threads).
- **Why it matters:** thread and memory exhaustion.
- **Good:** one managed executor per component, bounded queue, shutdown on context close.
- **Default severity:** high.

### JAVA-CONC-006 — CompletableFuture errors and executors

- **Look for:** `CompletableFuture.supplyAsync` without an explicit executor in code that runs under load (uses the common pool); `join()` or `get()` inside async chains; exceptions not handled (`exceptionally`, `handle`); futures never completed.
- **Why it matters:** starvation of the common pool and errors that vanish.
- **Default severity:** medium to high.

### JAVA-CONC-007 — Virtual threads: use for blocking I/O, not for CPU

- **Look for:** virtual threads used for CPU-bound loops without benefit; thread pools sized for virtual threads (virtual threads are not pooled; create one per task); `Executors.newVirtualThreadPerTaskExecutor()` wrapped in a fixed pool.
- **Why it matters:** no throughput gain for CPU work, and pooling defeats their design.
- **Default severity:** low to medium.

### JAVA-CONC-008 — Virtual threads: pinning inside synchronized

- **Look for:** blocking I/O, `Thread.sleep`, or lock waits inside `synchronized` blocks or methods on code that runs in virtual threads, on JDK 21 through 23.
- **Why it matters:** a virtual thread that blocks while holding a monitor pins its carrier thread. Throughput falls because carrier threads are exhausted.
- **Release note:** JDK 24 (JEP 491) removes monitor pinning. On JDK 21 to 23, replace `synchronized` with `ReentrantLock` around blocking calls, or keep blocking outside the monitor.
- **Evidence:** the `synchronized` block, the blocking call inside it, and the target release from the build.
- **Default severity:** medium on JDK 21 to 23; low on JDK 24 and later.

### JAVA-CONC-009 — Virtual threads: ThreadLocal caveats

- **Look for:** `ThreadLocal` used to carry request context, caches, or formatters with one entry per request on virtual threads; `ThreadLocal` values not removed in pooled (platform) threads.
- **Why it matters:** with a virtual thread per task, a `ThreadLocal` value is created per task and retained for the task's lifetime. Large values multiply memory use. Pooled platform threads leak values into later requests.
- **Good:** pass context explicitly; use `ScopedValue` (final in JDK 25, preview in 21 to 24) for immutable request-scoped data; call `ThreadLocal.remove()` in `finally` on pooled threads.
- **Default severity:** medium; high when values include identity or tenant data and pooled threads are used.

### JAVA-CONC-010 — Do not rely on thread names or identity

- **Look for:** logic keyed on `Thread.currentThread().getName()`; thread-based identity assumptions with virtual threads (names are often empty).
- **Default severity:** low.

### JAVA-CONC-011 — Concurrent collections are used for iteration under mutation

- **Look for:** iteration over a list or map while another thread modifies it, with no snapshot or concurrent collection.
- **Why it matters:** `ConcurrentModificationException` or silent inconsistency.
- **Default severity:** medium.

### JAVA-CONC-012 — Volatile is not a lock

- **Look for:** `volatile` fields used for compound updates (`count++`) or to protect multi-field invariants.
- **Default severity:** high.

### JAVA-CONC-013 — Timeouts on blocking calls

- **Look for:** `Future.get()`, `BlockingQueue.take()`, `Lock.lock()`, HTTP or JDBC calls with no timeout in request-handling code.
- **Why it matters:** threads wait forever when a dependency stalls.
- **Default severity:** medium.

## How to apply in review

1. Identify which code runs on more than one thread: request handlers, scheduled tasks, listeners, async stages.
2. Check the release from the build file before commenting on virtual threads or pinning.
3. For each lock, list what runs inside it.
4. Cite the field or method, and the interleaving that breaks it, stated in steps.
5. Do not recommend concurrency tooling for single-threaded code.
