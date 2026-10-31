---
title: Java knowledge pack index
source: Project-authored index of the java/ knowledge pack
version: Java 21 LTS and Java 25 LTS; Spring Framework 6.x / Spring Boot 3.x where applicable
reviewed: 2026-10
---

## Scope

Index of the Java pack used by `angela` (Java reviewer). Topic id is the file path without `.md`, for example `java/null-safety-optional`. Load a topic with `read_knowledge(topic)` only when the diff touches its area. Read `java/build-hygiene` first when feature advice depends on the target release.

## Rules

Topics:

- `java/null-safety-optional`: null returns, `Optional` use, `Objects` helpers, nullability annotations, boundary validation.
- `java/immutability-equality`: immutable value types, defensive copies, records, `equals`/`hashCode`, sealed hierarchies, `toString` leakage.
- `java/resources-exceptions`: try-with-resources, swallowed exceptions, exception types and cause preservation, `finally` hazards.
- `java/concurrency`: shared state, check-then-act, lock scope, interruption, executors, `CompletableFuture`, virtual threads (pinning on JDK 21 to 23, `ThreadLocal`).
- `java/collections-streams`: collection choice, mutation during iteration, stream side effects, parallel streams, collectors.
- `java/spring-core`: constructor injection, `@Transactional` self-invocation and boundaries, bean scopes, validation, controllers and DTOs, exception handling.
- `java/jpa-persistence`: N+1, multiple bag fetches, lazy loading, pagination, bulk operations, parameterised queries, migrations.
- `java/api-compat-logging`: public API compatibility, REST contract changes, Jakarta namespace, serialisation, logging levels and sensitive data.
- `java/testing`: assertion quality, Mockito misuse, Testcontainers, determinism, removed tests.
- `java/build-hygiene`: target release detection in Maven and Gradle, feature-by-release table, dependency and plugin hygiene.
- `java/performance`: evidence rules, unbounded growth, boxing, string building, regex compilation, I/O buffering, repeated setup.

Rule id prefixes: `JAVA-NULL`, `JAVA-IMM`, `JAVA-RES`, `JAVA-CONC`, `JAVA-COLL`, `JAVA-SPRING`, `JAVA-JPA`, `JAVA-API`, `JAVA-LOG`, `JAVA-TEST`, `JAVA-BUILD`, `JAVA-PERF`.

## How to apply in review

1. Run release detection (`java/build-hygiene` JAVA-BUILD-001). Do not suggest features above the detected release.
2. Identify frameworks from the build file and load the matching topics only.
3. Project conventions and skills override these defaults, but never lower a correctness or security finding below its floor.
4. Cite the rule id, the file, and the line in every finding.
5. Mark performance findings without evidence as low confidence.
