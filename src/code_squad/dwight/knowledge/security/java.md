---
title: Java and Spring security patterns
source: OWASP Java Security Cheat Sheet; OWASP Deserialization Cheat Sheet; OWASP XML External Entity Prevention Cheat Sheet; Spring Security reference documentation; CVE-2021-44228 (Log4Shell) and CVE-2017-5638 (Apache Struts OGNL) as historical examples; CWE-611, CWE-502, CWE-917
version: Java 21 LTS and Java 25 LTS; Spring Security 6.x (verify version in build file)
reviewed: 2026-10
---

## Scope

Security issues specific to Java and Spring: XML parsing, deserialisation, expression languages, JNDI and class loading, SQL built in JPQL and native queries, Spring Security configuration, and file handling. Pair with `injection.md`, `deserialisation.md`, `ssrf-path-traversal.md`, and `authn-session.md`. Code-quality concerns are reviewed by `angela` (`java` pack).

## Rules

### SEC-JAVA-001 — XML external entities (XXE)

- **Look for:** `DocumentBuilderFactory`, `SAXParserFactory`, `XMLInputFactory`, `TransformerFactory`, `SchemaFactory`, `XMLReader`, JAXB unmarshallers, and `DocumentBuilder` used on untrusted XML without disabling external entities and DTDs.
- **Why it matters:** file disclosure, SSRF, and denial of service through entity expansion (CWE-611, CWE-776).
- **Good:** set `XMLConstants.FEATURE_SECURE_PROCESSING`, disable `http://apache.org/xml/features/disallow-doctype-decl` where feasible, and disable external entity and DTD loading; for `XMLInputFactory`, set `SUPPORT_DTD` false and `IS_SUPPORTING_EXTERNAL_ENTITIES` false.
- **Default severity:** critical for untrusted XML with external entities allowed; high otherwise.

### SEC-JAVA-002 — Native deserialisation

- **Look for:** `ObjectInputStream.readObject`, `readUnshared`, or `XMLDecoder` on untrusted data; `Serializable` classes on remote interfaces (RMI, JMX, JMS object messages).
- **Why it matters:** gadget chains on the classpath lead to remote code execution. Log4Shell-class and commons-collections chains are examples of this pattern.
- **Good:** avoid native deserialisation for untrusted input; if unavoidable, use `ObjectInputFilter` with a strict allowlist of classes.
- **Default severity:** critical.
- **Detail:** `deserialisation.md`.

### SEC-JAVA-003 — Polymorphic JSON (Jackson and similar)

- **Look for:** `ObjectMapper.enableDefaultTyping`, `activateDefaultTyping` with broad validators, `@JsonTypeInfo(use = Id.CLASS)` on request types; `PolymorphicTypeValidator` that accepts all subtypes.
- **Default severity:** critical when the mapper reads untrusted JSON.

### SEC-JAVA-004 — YAML and other object-constructing formats

- **Look for:** SnakeYAML `new Yaml()` or `Yaml.load` with default constructor on untrusted input; XStream without a type allowlist; Hessian or Kryo with unrestricted classes.
- **Good:** `SafeConstructor` for SnakeYAML; XStream `allowTypes` with explicit names.
- **Default severity:** critical for untrusted input.

### SEC-JAVA-005 — Expression language injection (SpEL, OGNL, MVEL, EL)

- **Look for:** `SpelExpressionParser.parseExpression(input)` on input; `ExpressionParser` used on request parameters or stored values; OGNL evaluation of user values; Spring `@PreAuthorize` or `@Value` with input-derived expressions; Jakarta EL evaluated on input.
- **Why it matters:** expression evaluation executes code (CWE-917). Historical example: CVE-2017-5638 in Struts OGNL handling.
- **Good:** use `SimpleEvaluationContext` for SpEL on data binding; never parse user input as an expression; use fixed templates with data parameters.
- **Default severity:** critical when reachable.

### SEC-JAVA-006 — JNDI lookups and remote class loading

- **Look for:** `InitialContext.lookup`, `JdbcRowSetImpl`, `JndiLookup` or other lookup mechanisms receiving input; logging frameworks configured to resolve lookups from message content; `URLClassLoader` loading from input-supplied URLs.
- **Why it matters:** JNDI injection loads remote code. Log4Shell (CVE-2021-44228) exploited message-based lookups. Check the logging library version and configuration when logs include user-controlled text.
- **Good:** upgrade to patched logging versions, disable lookups, do not construct names from input, and restrict lookup protocols.
- **Default severity:** critical when input reaches a lookup; high when the library version is vulnerable and input reaches logs (triage per `dependency-triage.md`).
- **CWE:** CWE-917, CWE-74, CWE-502.

### SEC-JAVA-007 — SQL in JPQL and native queries

- **Look for:** `entityManager.createQuery("... " + input)`, `createNativeQuery` with concatenation, Spring Data `@Query` with `nativeQuery = true` built from input, Criteria API with raw strings in `like` or `order by`.
- **Good:** named parameters (`:name`) or positional parameters; allowlist for sort and column names; `Sort` built from validated property names.
- **Default severity:** critical if unauthenticated; high otherwise.
- **CWE:** CWE-89.

### SEC-JAVA-008 — Spring Security configuration

- **Look for:** `csrf().disable()` on cookie-authenticated applications; `permitAll()` on broad paths (`/**`, `/api/**`) followed by a narrower `authenticated()` rule that is never reached; `antMatchers` or `requestMatchers` ordered such that a general rule matches first; `@EnableMethodSecurity` missing where `@PreAuthorize` is used; `hasRole` and `hasAuthority` confused (`ROLE_` prefix); CORS allowing all origins with credentials; `anyRequest().permitAll()`.
- **Why it matters:** access control gaps (A01). Ordering and matcher mistakes are the most common Spring Security defects.
- **Good:** deny by default with `anyRequest().authenticated()`; explicit allowlist for public paths; method security for object-level checks.
- **Default severity:** critical for `permitAll` on sensitive paths; high otherwise.
- **CWE:** CWE-862, CWE-352, CWE-284.

### SEC-JAVA-009 — Spring Actuator and management endpoints

- **Look for:** `management.endpoints.web.exposure.include=*` or `env`, `heapdump`, `threaddump`, `loggers`, `shutdown` exposed; management port on the public interface; no authentication on actuator paths.
- **Why it matters:** environment and heap dumps reveal secrets; `shutdown` and `loggers` change the running service.
- **Good:** expose only `health` and `info` publicly; bind management to an internal port; secure other endpoints.
- **Default severity:** high; critical for `heapdump` or `env` reachable without authentication.
- **CWE:** CWE-200, CWE-489.

### SEC-JAVA-010 — Spring Boot devtools and debug settings

- **Look for:** `spring-boot-devtools` on the production classpath; `debug=true`; `server.error.include-stacktrace=always`; `server.error.include-message=always`.
- **Default severity:** medium to high.
- **CWE:** CWE-489, CWE-209.

### SEC-JAVA-011 — Path traversal and archive extraction

- **Look for:** `Paths.get(base, input)` without containment; `ZipInputStream` extraction without entry name checks; `File.getCanonicalPath` checks missing; `Files.copy` into directories derived from input.
- **Detail:** `ssrf-path-traversal.md` SEC-PATH-001 and SEC-PATH-003.
- **Default severity:** high.

### SEC-JAVA-012 — Weak random and crypto in Java

- **Look for:** `java.util.Random` for tokens; `MessageDigest.getInstance("MD5")` or `"SHA-1"` for security; `Cipher.getInstance("AES")` without a mode (defaults vary by provider); `TrustManager` accepting all; `HostnameVerifier` returning true.
- **Detail:** `crypto.md`.
- **Default severity:** high.

### SEC-JAVA-013 — Java RMI, JMX, and JMS exposure

- **Look for:** RMI registries or JMX remote on public interfaces without authentication and TLS; JMX `com.sun.management.jmxremote.authenticate=false`; JMS object messages from untrusted producers.
- **Default severity:** critical when reachable from untrusted networks.
- **CWE:** CWE-306, CWE-502.

### SEC-JAVA-014 — Reflection and dynamic class loading from input

- **Look for:** `Class.forName(input)`, `newInstance` on input-selected classes, `ScriptEngine.eval(input)` (Nashorn is removed in JDK 15; check for other script engines).
- **Default severity:** critical when input selects the class or script.
- **CWE:** CWE-470, CWE-94.

### SEC-JAVA-015 — Java cookies, sessions, and HTTP headers

- **Look for:** `Cookie` objects without `setHttpOnly(true)` or `setSecure(true)`; `SameSite` not set through the container or framework; session fixation protections disabled in Spring Security (`sessionFixation().none()`).
- **Default severity:** medium to high.
- **Detail:** `authn-session.md`, `xss-csrf.md`.

## How to apply in review

1. Identify the XML, deserialisation, expression, and lookup calls in the diff.
2. For Spring applications, read the security configuration class in full, including rule ordering.
3. For logging-library changes, check the version and the lookup configuration (triage per `dependency-triage.md`).
4. Cite the class, method, and line, and the input source.
5. Do not include payloads or gadget names in findings. Describe the mechanism and the mitigation.
