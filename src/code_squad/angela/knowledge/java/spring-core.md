---
title: Spring core: dependency injection, transactions, scopes, validation, controllers
source: Spring Framework reference documentation (Core, Data Access - Transaction Management, Validation, Web MVC); Spring Boot reference documentation
version: Spring Framework 6.x and Spring Boot 3.x (verify the major in the build file); Java 17+ baseline
reviewed: 2026-10
unverified-edition: true
---

## Scope

Spring Framework and Spring Boot application code: bean wiring, `@Transactional` behaviour, bean scopes, bean validation, controller and DTO design, and configuration. Applies only when Spring is detected in `pom.xml` or `build.gradle*`. Persistence-specific rules are in `jpa-persistence`. Security configuration is covered by `dwight` (`java.md`).

## Rules

### JAVA-SPRING-001 — Constructor injection

- **Look for:** `@Autowired` on fields; setter injection for required dependencies; `new` of a service inside another service that should be a bean.
- **Why it matters:** fields hide dependencies, prevent immutability, and make tests need reflection or the container.
- **Good:** `private final OrderRepository orders;` with one constructor (Spring injects it without `@Autowired` in current versions).
- **Default severity:** low to medium.

### JAVA-SPRING-002 — Self-invocation bypasses @Transactional and proxies

- **Look for:** a method annotated `@Transactional`, `@Async`, `@Cacheable`, or `@Retryable` called from another method in the same class via `this`.
- **Why it matters:** Spring applies these through proxies. A call through `this` skips the proxy, so the transaction or cache does not apply. Behaviour looks correct in a quick test and fails in production paths that take a different route.
- **Evidence:** the annotated method, the internal call site, and the proxy mode in use.
- **Good:** move the method to another bean, or inject the bean into itself, or use `AopContext` only if the project already does.
- **Default severity:** high.

### JAVA-SPRING-003 — @Transactional boundaries

- **Look for:** `@Transactional` on private or package-private methods (not applied by default proxies); on controllers (transaction scope spans rendering); long external calls (HTTP, messaging) inside a transaction; catching exceptions inside a transactional method that should roll back; `readOnly = true` on methods that write.
- **Why it matters:** rollbacks do not happen, connections are held during network I/O, or writes are lost.
- **Rollback rule:** by default, Spring rolls back on unchecked exceptions and `Error`, not on checked exceptions. Verify `rollbackFor` for checked exceptions.
- **Evidence:** the annotation, the method visibility, and the call inside.
- **Default severity:** high.

### JAVA-SPRING-004 — Transactions and asynchronous code

- **Look for:** `@Async` methods that expect the caller's transaction to propagate; `CompletableFuture` chains that call transactional methods on a different thread without a transaction.
- **Why it matters:** the work runs without the expected transaction or with a different one.
- **Default severity:** medium to high.

### JAVA-SPRING-005 — Bean scopes

- **Look for:** `@Scope("prototype")` injected into singletons without `ObjectProvider` or a proxy; mutable state in singleton beans (fields written per request); `@RequestScope` or `@SessionScope` beans injected into singletons without a scoped proxy.
- **Why it matters:** a singleton holding per-request state leaks data between users (CWE-362 class issues).
- **Evidence:** the bean definition, the mutable field, and the requests that share it.
- **Default severity:** high for shared mutable state; medium otherwise.

### JAVA-SPRING-006 — Bean validation at the boundary

- **Look for:** controllers accepting `@RequestBody` without `@Valid`; `@Valid` on request objects with missing constraints on required fields; validation logic duplicated in service and controller; `@Validated` missing where method-level constraints are used.
- **Why it matters:** unvalidated input reaches the domain. See `SEC-INJECT-*` for downstream effects.
- **Good:** `public ResponseEntity<Dto> create(@Valid @RequestBody CreateOrder request)`
- **Default severity:** medium; high for public endpoints.

### JAVA-SPRING-007 — Controllers do not expose entities

- **Look for:** JPA entities returned from controllers or accepted as request bodies; DTOs that mirror entity fields including internal ids, flags, or password hashes.
- **Why it matters:** accidental exposure of fields, lazy-loading exceptions during serialisation, and API coupling to the schema.
- **Good:** separate request and response records; map in a service or mapper.
- **Default severity:** high when sensitive fields are exposed; medium otherwise.

### JAVA-SPRING-008 — Controllers are thin

- **Look for:** business rules, transactions, or repository calls directly in controllers; HTTP status logic mixed into services.
- **Default severity:** low to medium.

### JAVA-SPRING-009 — Configuration properties are typed and validated

- **Look for:** `@Value("${...}")` scattered across beans for many related settings; missing defaults where the application fails at runtime; secrets with default values in source.
- **Good:** `@ConfigurationProperties` records with `@Validated`.
- **Default severity:** low to medium; high for default secrets (see `SEC-SECRETS-*`).

### JAVA-SPRING-010 — Exception handling is centralised

- **Look for:** each controller with its own `try/catch` returning inconsistent error bodies; `@ExceptionHandler` that returns stack traces or internal messages; missing handler for `MethodArgumentNotValidException`.
- **Why it matters:** inconsistent API responses and information disclosure (CWE-209).
- **Good:** one `@RestControllerAdvice` with problem-detail responses (RFC 9457 via Spring's `ProblemDetail`).
- **Default severity:** medium.

### JAVA-SPRING-011 — Component scanning and bean overrides

- **Look for:** beans defined in multiple places with the same name; `@Primary` added to hide a conflict; test configuration leaking into main configuration.
- **Default severity:** low.

### JAVA-SPRING-012 — Actuator and debug endpoints

- **Look for:** `management.endpoints.web.exposure.include=*`; environment or heap-dump endpoints reachable without authentication.
- **Why it matters:** configuration and secret disclosure. Cross-reference `SEC-CONFIG-*` and `dwight` `security/java` (SEC-JAVA-009).
- **Default severity:** high.

### JAVA-SPRING-013 — Startup and lifecycle hooks

- **Look for:** long-running work in `@PostConstruct`; blocking startup on external services without timeouts; `@EventListener` methods that run transactional writes before commit.
- **Default severity:** low to medium.

## How to apply in review

1. Confirm Spring Boot and Framework versions in the build file.
2. For every `@Transactional`, check visibility, call path (self-invocation), and the work inside.
3. For every controller, check input validation, the body type, and the error response.
4. For singletons, check for mutable instance state.
5. Cite the class, method, and the call path that bypasses the annotation.
