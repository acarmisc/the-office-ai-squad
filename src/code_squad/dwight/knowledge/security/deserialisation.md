---
title: Insecure deserialisation
source: OWASP Deserialization Cheat Sheet; OWASP Top 10:2025 A08 (Software or Data Integrity Failures); CWE-502
version: OWASP Top 10:2025 A08; CWE-502 (rank 15 in CWE Top 25 2025)
reviewed: 2026-10
---

## Scope

Turning serialised data from outside the trust boundary back into objects or executable structures. Covers Java object serialisation and polymorphic JSON, Python `pickle` and YAML loaders, PHP `unserialize`, .NET formatters, and YAML or XML loaders with object construction. Language specifics for Java are in `java.md`.

## Rules

### SEC-DESER-001 — Native object deserialisation of untrusted input

- **Look for:** `ObjectInputStream.readObject` on network, file, cookie, or message input; `pickle.loads`, `marshal.loads`, `yaml.load` without a safe loader; `unserialize` in PHP on request data; `BinaryFormatter` in .NET.
- **Why it matters:** the deserialiser constructs objects and runs code from gadget chains. This is typically remote code execution.
- **Evidence:** the input source, the call, and whether the data crosses a trust boundary.
- **Good:** avoid native serialisation for untrusted input. Use a data-only format (JSON with a fixed schema) and map to known types.
- **Default severity:** critical.

### SEC-DESER-002 — Polymorphic type handling in JSON

- **Look for:** Jackson `enableDefaultTyping` or `@JsonTypeInfo` with `Id.CLASS` on input types; Gson or other libraries constructing arbitrary classes from a type field; JSON that names a class to instantiate.
- **Why it matters:** the same gadget risk as native serialisation.
- **Good:** use `Id.NAME` with an explicit allowlist of subtypes (`PolymorphicTypeValidator`), or a closed set of DTOs.
- **Default severity:** critical when untrusted input reaches the type resolver.

### SEC-DESER-003 — Safe loaders for YAML and similar formats

- **Look for:** `yaml.load` (PyYAML) without `SafeLoader`; SnakeYAML `new Yaml()` on untrusted input (default constructor can instantiate classes); YAML anchors and tags from untrusted sources.
- **Good:** `yaml.safe_load`; SnakeYAML with `SafeConstructor`.
- **Default severity:** high to critical.

### SEC-DESER-004 — XML with object binding

- **Look for:** JAXB, XMLDecoder (`java.beans.XMLDecoder`), XStream without a type allowlist, and similar tools constructing objects from XML. Also see XXE in `java.md`.
- **Default severity:** critical for XMLDecoder and unrestricted XStream.

### SEC-DESER-005 — Integrity before parse

- **Look for:** data read from cookies, hidden fields, caches, or queues that is deserialised before its signature or MAC is checked; signature checks that happen after parsing.
- **Good:** verify the MAC or signature over the raw bytes first, with a constant-time compare, then parse.
- **Default severity:** high.

### SEC-DESER-006 — Gadget exposure through dependencies

- **Look for:** libraries known to host gadget chains on the classpath (commons-collections versions with known gadgets, and similar) when deserialisation is reachable. Use dependency triage (`dependency-triage.md`) to assess reachability.
- **Default severity:** follows reachability; high when native deserialisation of untrusted input is reachable.

### SEC-DESER-007 — Deserialisation filters

- **Look for:** absence of Java serialisation filters (`ObjectInputFilter`) where native deserialisation remains necessary for trusted internal streams; filters configured as allow-all.
- **Good:** set a strict `jdk.serialFilter` or per-stream filter that allows named classes only.
- **Default severity:** medium.

### SEC-DESER-008 — Deserialising data that is not needed

- **Look for:** full object graphs deserialised to read one field; large inputs parsed without size limits (resource exhaustion, CWE-400).
- **Default severity:** low to medium.

## How to apply in review

1. Identify every parse call that builds objects from external data.
2. For each, identify the format and whether the loader constructs arbitrary types.
3. Check for a signature or MAC before the parse, if the data is stored outside the server.
4. Cite the call and the type-binding setting.
5. Do not describe gadget chains in findings. State the risk class and the mitigation.
