---
title: Security knowledge pack index
source: Project-authored index of the security/ knowledge pack
version: OWASP Top 10:2025; OWASP API Security Top 10:2023; OWASP ASVS 5.0 (unverified-edition); OWASP Top 10 for LLM Applications 2025; CWE Top 25 2025
reviewed: 2026-10
---

## Scope

Index of the security pack used by `dwight` (security reviewer). Topic id is the file path without `.md`, for example `security/injection`. Load topics with `read_knowledge(topic)` only when the diff touches their area. Start with `security/owasp-top10` for category framing and `security/cwe-top25` for prioritisation.

## Rules

Topics:

- `security/owasp-top10`: OWASP Top 10:2025 categories A01 to A10 with representative CWEs and routing to detail topics.
- `security/owasp-api-top10`: OWASP API Security Top 10:2023 for HTTP APIs (BOLA, BOPLA, BFLA, resource consumption, SSRF, misconfiguration, inventory, unsafe consumption).
- `security/owasp-asvs`: ASVS control families and verification levels; edition marked unverified.
- `security/owasp-llm-top10`: OWASP Top 10 for LLM Applications 2025 for code that calls or wraps models and agents.
- `security/cwe-top25`: CWE Top 25 2025 ranking with review cues.
- `security/injection`: SQL, NoSQL, OS command, argument, LDAP, XPath, template and expression injection.
- `security/xss-csrf`: output encoding, stored and DOM XSS, URL schemes, CSP, CSRF, cookie attributes, CORS.
- `security/ssrf-path-traversal`: outbound request control, address validation, redirects, path containment, archive extraction.
- `security/deserialisation`: native and object-binding deserialisation across Java, Python, PHP, .NET, YAML, XML.
- `security/authn-session`: credential storage, brute force, MFA, password reset, sessions, JWT validation, OAuth and OIDC flows.
- `security/secrets-logging`: secret handling, secrets in CI and images, sensitive data in logs and telemetry. Report location only.
- `security/crypto`: algorithms, modes, nonces, randomness, password hashing, key handling, certificate and TLS validation.
- `security/docker-k8s-hardening`: CIS-style container and Kubernetes checks (user, privileges, capabilities, RBAC, network, images).
- `security/supply-chain-ssdf-slsa`: lockfiles, dependency confusion, install scripts, pinned CI actions, provenance, signing, SBOM.
- `security/node-react`: prototype pollution, mass assignment, command execution, npm lifecycle scripts, browser sinks, postMessage, token storage.
- `security/java`: XXE, deserialisation, expression languages, JNDI, JPQL and native SQL, Spring Security configuration, actuator exposure.
- `security/dependency-triage`: ranking (KEV, EPSS, CVSS, reachability), severity mapping, offline rule, redaction of dependency findings.

Rule id prefixes: `SEC-ACCESS`, `SEC-CONFIG`, `SEC-SUPPLY`, `SEC-CRYPTO`, `SEC-INJECT`, `SEC-DESIGN`, `SEC-AUTHN`, `SEC-INTEG`, `SEC-LOG`, `SEC-ERR`, `SEC-API`, `SEC-XSS`, `SEC-CSRF`, `SEC-SSRF`, `SEC-PATH`, `SEC-DESER`, `SEC-SECRETS`, `SEC-DOCKER`, `SEC-K8S`, `SEC-NODE`, `SEC-JAVA`, `SEC-LLM`, `SEC-CWE`, `SEC-ASVS`, `SEC-DEP`.

## How to apply in review

1. Build the threat model for the change first: entry points, trust boundaries, sensitive data, and privileges.
2. Load the topics that match the changed code. Load `security/dependency-triage` for any dependency change.
3. Report only findings with an attack path in the diff. Map each finding to a CWE and, for dependencies, a CVE or advisory id.
4. Apply the offline rule (`security/dependency-triage` SEC-DEP-004) before writing the verdict.
5. Never print secret values, working exploit payloads, or gadget chain names. Report location and mechanism.
6. Route pipeline and runtime-operations questions to `darryl` with the rule ids.
