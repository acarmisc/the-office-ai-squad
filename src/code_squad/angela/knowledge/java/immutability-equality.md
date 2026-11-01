---
title: Immutability, equality and records
source: Oracle Java SE 21 Language Specification (Records, Sealed Classes); Effective Java 3rd edition (Bloch), Items 10, 11, 17; JEP 395 (Records, final in Java 16)
version: Java 21 LTS; Java 25 LTS (current)
reviewed: 2026-10
---

## Scope

Mutable state, defensive copies, `equals`, `hashCode`, `toString`, `Comparable`, and the use of records and sealed hierarchies for value types. Applies to domain objects, DTOs, value objects, and anything used as a map key or in a set.

## Rules

### JAVA-IMM-001 — Value objects are immutable

- **Look for:** value classes with public setters or non-final fields; collections returned without copying; `this` leaked during construction.
- **Why it matters:** shared mutable values change under other callers, and hash-based collections break.
- **Evidence:** the field, the setter or accessor, and a caller that mutates the shared instance.
- **Good:** a `record Money(BigDecimal amount, Currency currency) { }` with compact-constructor validation.
- **Default severity:** medium; high when the object is cached, shared across threads, or used as a key.

### JAVA-IMM-002 — Defensive copies at boundaries

- **Look for:** constructors that store a caller's `List`, `Date`, or array directly; getters returning internal mutable collections or arrays.
- **Why it matters:** the caller keeps a reference and can change the object's state later.
- **Good:** `this.items = List.copyOf(items);` and `return items;` for an already immutable field.
- **Default severity:** medium.

### JAVA-IMM-003 — Records for data carriers

- **Look for:** hand-written DTOs with boilerplate `equals`, `hashCode`, and `toString` that could be a record; records used where the type must be mutable (JPA entities, frameworks that require no-arg constructors and setters).
- **Why it matters:** less code to get wrong. Records are final and have value semantics, which suits DTOs but not entities.
- **Requires:** Java 16 or later (final). Check the release before recommending.
- **Default severity:** low.

### JAVA-IMM-004 — Compact constructors validate invariants

- **Look for:** records that accept invalid states (negative quantities, null required fields); validation duplicated in factories.
- **Good:** `record Quantity(int value) { Quantity { if (value < 0) throw new IllegalArgumentException(...); } }`
- **Default severity:** medium.

### JAVA-IMM-005 — equals and hashCode are consistent

- **Look for:** `equals` overridden without `hashCode`; `hashCode` using mutable fields; `equals` using `instanceof` on a non-final class with subclass-sensitive logic; `equals` comparing floating-point fields with `==`.
- **Why it matters:** `HashSet` and `HashMap` lose elements; `equals` symmetry breaks across subclasses.
- **Evidence:** the two methods and the fields used in each.
- **Default severity:** high when the type is used in hash-based collections.

### JAVA-IMM-006 — Identity for entities, value for values

- **Look for:** JPA entities with `equals` based on generated ids that change after persist; entities with `equals` over all fields including collections (lazy loading side effects).
- **Why it matters:** an entity placed in a `Set` before persist changes hash code after persist.
- **Good:** equality on a business key or on identity with a stable `hashCode` (constant) for entities, documented.
- **Default severity:** medium.

### JAVA-IMM-007 — toString does not leak secrets

- **Look for:** `toString` including passwords, tokens, personal data, or full payloads of sensitive objects; records with sensitive components that print in logs.
- **Why it matters:** secrets written to logs (CWE-532). Records generate `toString` automatically, including all components.
- **Good:** override `toString` to mask the sensitive component, or keep the sensitive field out of the record.
- **Default severity:** high. Cross-reference `SEC-SECRETS-*`.

### JAVA-IMM-008 — Sealed hierarchies for closed sets of variants

- **Look for:** open class hierarchies used to model a fixed set of result types, where switch or if-chains must handle every case; `default` branches that hide missing variants.
- **Why it matters:** the compiler checks exhaustiveness for sealed types, catching new variants that are not handled.
- **Requires:** `sealed` from Java 17; exhaustive pattern `switch` from Java 21.
- **Default severity:** low.

### JAVA-IMM-009 — Mutable static state is avoided

- **Look for:** `public static` non-final fields; static `Map` or `List` caches without bounds or synchronisation; `static final` collections that are modifiable and exposed.
- **Why it matters:** hidden shared state across tests and requests.
- **Default severity:** medium.

### JAVA-IMM-010 — Comparable and ordering are consistent with equals

- **Look for:** `compareTo` that returns 0 for objects that `equals` says are different (breaks `TreeSet`); subtraction-based comparisons that overflow.
- **Good:** `Integer.compare(a, b)` and `Comparator.comparing(...)`.
- **Default severity:** medium.

## How to apply in review

1. Look for mutable fields and public collections in new types first.
2. Check `equals` and `hashCode` as a pair. Check their field lists match.
3. For records, confirm the Java release supports them and that no framework needs a mutable form.
4. Cite the class, field, and the caller or collection that exposes the defect.
5. Do not request immutability for internal, short-lived objects that never escape a method.
