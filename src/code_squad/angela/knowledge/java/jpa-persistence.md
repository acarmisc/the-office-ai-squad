---
title: JPA and Hibernate persistence
source: Jakarta Persistence 3.1/3.2 specification; Hibernate ORM 6.x User Guide (fetching, batch fetching, pagination); Spring Data JPA reference documentation
version: Jakarta Persistence 3.1+ with Hibernate ORM 6.x (verify in dependency tree); Java 17+ baseline
reviewed: 2026-10
unverified-edition: true
---

## Scope

JPA entities, associations, fetching, queries, pagination, transactions as seen from persistence code, and schema-related review points. Applies when `jakarta.persistence` or `javax.persistence` is on the classpath. Spring transaction placement is in `spring-core`.

## Rules

### JAVA-JPA-001 — N+1 queries

- **Look for:** a repository call that returns a list, followed by a loop that touches a lazy association on each element; `@OneToMany` or `@ManyToOne` fetched lazily and accessed in a controller, template, or mapper.
- **Why it matters:** one query becomes one plus N queries. Latency grows with row count and the bug appears only with real data.
- **Evidence:** the loop, the association accessed, and the SQL log showing repeated statements (`spring.jpa.show-sql` or Hibernate statistics).
- **Good:** `@EntityGraph(attributePaths = "items")` on the repository method, a `JOIN FETCH` in JPQL for a single collection, or `@BatchSize` / `hibernate.default_batch_fetch_size`.
- **Default severity:** high on list endpoints; medium on admin or bounded lists.

### JAVA-JPA-002 — Multiple collection fetches

- **Look for:** `JOIN FETCH` on two or more `List` (bag) associations in one query; `MultipleBagFetchException`; workaround by changing collections to `Set` without understanding the cartesian product.
- **Why it matters:** cartesian explosion of rows, and duplicate data in results.
- **Good:** fetch one collection per query, or use `Set` with clear semantics, or batch fetch.
- **Default severity:** high.

### JAVA-JPA-003 — Lazy loading outside the session

- **Look for:** lazy associations accessed after the transaction or session closes (for example in mapping after service return, or in serialisation); `open-in-view` left enabled while the code relies on it.
- **Why it matters:** `LazyInitializationException` in production paths, or hidden queries during serialisation.
- **Good:** map to DTOs inside the transaction using fetch joins or projections; set `spring.jpa.open-in-view=false` where the team has adopted explicit fetching.
- **Default severity:** medium to high.

### JAVA-JPA-004 — Eager fetching by default

- **Look for:** `FetchType.EAGER` on `@OneToMany` or `@ManyToMany`; `@ManyToOne` or `@OneToOne` left at the default eager fetch when the association is rarely needed.
- **Why it matters:** unnecessary joins and loads on every query.
- **Note:** `@ManyToOne` and `@OneToOne` default to eager in JPA. Recommend lazy plus explicit fetching where the usage pattern is known.
- **Default severity:** medium.

### JAVA-JPA-005 — Pagination on collections

- **Look for:** `findAll()` or unbounded queries on tables that grow; `Pageable` without a maximum page size; in-memory pagination (`subList`) after loading all rows; `JOIN FETCH` combined with pagination on a collection (Hibernate warns and paginates in memory).
- **Why it matters:** memory exhaustion and slow queries. Hibernate applies in-memory pagination when fetching a collection with `setFirstResult`, which loads all rows.
- **Good:** paginate the root entity, then fetch the collection with `@BatchSize` or a second query for the page ids. Cap `size` in the controller.
- **Default severity:** high on user-facing lists.

### JAVA-JPA-006 — Keyset pagination for deep pages

- **Look for:** offset pagination on very large or frequently changing tables used for infinite scroll or exports.
- **Why it matters:** offset cost grows with depth, and inserts shift pages.
- **Default severity:** low to medium.

### JAVA-JPA-007 — Entity equality and identity

- **Look for:** entities in hash sets before persist; `equals` on all fields including associations (see `immutability-equality` JAVA-IMM-006).
- **Default severity:** medium.

### JAVA-JPA-008 — Bulk operations and the persistence context

- **Look for:** loops that save thousands of entities without flushing and clearing; `saveAll` on large lists with no batching configuration; `@Modifying` queries executed without `clearAutomatically` when entities are read afterwards in the same transaction.
- **Why it matters:** memory growth and stale entities after bulk updates.
- **Good:** `hibernate.jdbc.batch_size`, periodic `flush()` and `clear()`, or JPQL bulk updates with `clearAutomatically = true`.
- **Default severity:** medium to high.

### JAVA-JPA-009 — Native and JPQL queries use parameters

- **Look for:** string concatenation of user input into JPQL, HQL, or native SQL; `createQuery` with `+` expressions; `Sort` built from request parameters without an allowlist.
- **Why it matters:** SQL and JPQL injection (CWE-89). Cross-reference `SEC-INJECT-*`.
- **Good:** named or positional parameters; `Sort` validated against an allowlist of property names.
- **Default severity:** high.

### JAVA-JPA-010 — Schema changes are migrated

- **Look for:** `spring.jpa.hibernate.ddl-auto=update` or `create` in non-test configuration; entity changes without a migration script (Flyway or Liquibase); column renames that drop data.
- **Why it matters:** production schema drifts from code, and destructive changes run at startup.
- **Default severity:** high in production profiles.

### JAVA-JPA-011 — Column types and precision

- **Look for:** money stored as `double` or `float`; timestamps as `String`; missing `length` or `precision` on large text or decimal columns; `@Enumerated` without `EnumType.STRING` (ordinal changes break data).
- **Default severity:** medium to high (money and enum ordinal).

### JAVA-JPA-012 — Optimistic locking for concurrent updates

- **Look for:** entities updated by concurrent requests with no `@Version`; lost-update paths in read-modify-write code.
- **Good:** `@Version private long version;` and handling of `OptimisticLockException`.
- **Default severity:** medium.

### JAVA-JPA-013 — Timeouts and read-only transactions

- **Look for:** long report queries without `readOnly` hints; queries without a timeout in shared code paths.
- **Default severity:** low.

## How to apply in review

1. Identify the repository methods and the loops that consume their results.
2. Check each association's fetch type and where it is accessed.
3. For each list endpoint, check the page size cap and the query shape.
4. Request SQL logs or Hibernate statistics as evidence when the N+1 cannot be proven from code alone; mark the finding medium confidence otherwise.
5. Cite the repository method, entity field, and the access site.
