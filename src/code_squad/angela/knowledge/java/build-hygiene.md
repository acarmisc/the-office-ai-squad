---
title: Build hygiene and target release detection (Maven and Gradle)
source: Apache Maven compiler plugin documentation (release, source, target); Gradle Java plugin documentation (toolchains, release option); Oracle Java SE release notes and JEP index
version: Maven 3.9+, Gradle 8.x; Java 21 LTS and Java 25 LTS (current)
reviewed: 2026-10
unverified-edition: true
---

## Scope

Build configuration for Java projects: detecting the target release, using it to constrain language feature advice, dependency management, and reproducibility. Use this file before recommending any language feature. Applies to `pom.xml`, `build.gradle`, `build.gradle.kts`, `gradle.properties`, `settings.gradle*`, and wrapper files.

## Rules

### JAVA-BUILD-001 — Detect the target release before advising

- **Look for:** nothing in code; check the build file in this order.
- **Maven:** `maven.compiler.release` property; then `<release>` in `maven-compiler-plugin` configuration; then `maven.compiler.source` and `target` (or `<source>`/`<target>`). If the project inherits from `spring-boot-starter-parent`, check the `java.version` property, which the parent maps to the compiler release.
- **Gradle:** `java { toolchain { languageVersion = JavaLanguageVersion.of(N) } }`; then `sourceCompatibility` and `targetCompatibility`; then `options.release` on `JavaCompile` tasks.
- **Why it matters:** suggesting `record` or pattern `switch` in a Java 11 project produces code that does not compile.
- **Evidence:** the file and property, and the value. If the value cannot be determined, state "release unknown" and restrict advice to Java 8 features that are safe across releases.
- **Default severity:** not a finding by itself; a prerequisite for feature advice. Report a finding when the diff uses a feature above the detected release (severity high, compile failure).

### JAVA-BUILD-002 — Feature availability by release

Use this table to check feature advice. Features marked preview require `--enable-preview` and are not for production code.

| Feature | Release | Status |
|---|---|---|
| `var` local variable inference | 10 | Final |
| `List.of`, `Set.of`, `Map.of` | 9 | Final |
| `Optional.isEmpty`, `String.isBlank`, `strip`, `lines` | 11 | Final |
| Switch expressions and `yield` | 14 | Final |
| Text blocks | 15 | Final |
| Records | 16 | Final |
| `instanceof` pattern matching | 16 | Final |
| `Stream.toList()` | 16 | Final |
| Sealed classes | 17 | Final |
| Pattern matching for `switch` | 21 | Final |
| Record patterns | 21 | Final |
| Virtual threads | 21 | Final |
| Sequenced collections | 21 | Final |
| Unnamed patterns and variables (`_`) | 22 | Final |
| Stream gatherers | 24 | Final (preview in 22, 23) |
| Synchronise virtual threads without pinning | 24 | Final (JEP 491) |
| Flexible constructor bodies | 25 | Final |
| Scoped values | 25 | Final (preview 21 to 24) |
| Module import declarations | 25 | Final |
| Compact source files and instance main methods | 25 | Final |
| Structured concurrency | Any | Preview or incubator; do not recommend for production |
| String templates | Any | Preview (JDK 21 to 23); not final; do not recommend for production |

Language features in this table are the scope of JAVA-BUILD-001 checks. Library APIs (for example `HttpClient` in 11, `java.time` in 8) follow the same release check.

- **Default severity:** high when a feature above the detected release is used.

### JAVA-BUILD-003 — Use the same release for compile and runtime

- **Look for:** `release` set to 17 while the Docker base image or CI runner uses JDK 21 without the flag; toolchain set in Gradle but not in CI; `source` and `target` without `release` (compiles against the wrong API set).
- **Why it matters:** classes compiled against newer APIs fail at runtime on the older JVM.
- **Good:** set `release` (not only `source` and `target`), and align the runtime image with the same major version.
- **Default severity:** medium.

### JAVA-BUILD-004 — Dependency versions are managed

- **Look for:** versions repeated across modules instead of a parent POM, BOM, or `libs.versions.toml`; ranges such as `[1.0,)` or `+`; snapshot dependencies in release branches; mixed major versions of one library family.
- **Why it matters:** inconsistent classpaths and unreproducible builds.
- **Default severity:** medium.

### JAVA-BUILD-005 — Reproducible builds

- **Look for:** Gradle without a lockfile where the project requires locking; Maven without the wrapper (`mvnw`) when CI depends on a specific version; `gradle-wrapper.properties` changed without a reason.
- **Default severity:** low to medium.

### JAVA-BUILD-006 — Test and build scopes

- **Look for:** test libraries in `compile` or `implementation` scope; runtime-only dependencies missing from the runtime classpath; `provided` scope for libraries that must exist at runtime in the deployable.
- **Default severity:** medium.

### JAVA-BUILD-007 — Plugins are pinned and minimal

- **Look for:** plugin versions without a pin; plugins executing shell commands on build without review; `exec` tasks added to build without justification.
- **Why it matters:** supply-chain exposure (see `dwight` supply chain rules) and reproducibility.
- **Default severity:** medium.

### JAVA-BUILD-008 — Compiler warnings are not suppressed silently

- **Look for:** `-Xlint:none` or `-nowarn`; `@SuppressWarnings("unchecked")` on large scopes without comment; `-Werror` removed.
- **Default severity:** low.

### JAVA-BUILD-009 — Javadoc and generated sources

- **Look for:** generated sources edited by hand; build steps that generate sources not in the source set; `module-info.java` added to a project without modular build setup.
- **Default severity:** low.

## How to apply in review

1. Run the release detection in JAVA-BUILD-001 first and record the result in your reasoning.
2. Check each new language feature in the diff against the table.
3. Check that the runtime image uses the same major version as `release`.
4. For dependency changes, state the module and version change and route vulnerability questions to `dwight`.
5. Cite the build file and property name that establishes the release.
