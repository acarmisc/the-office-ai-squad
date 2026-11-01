---
title: OWASP API Security Top 10 (2023) for review
source: OWASP API Security Top 10 2023 (owasp.org/API-Security)
version: OWASP API Security Top 10:2023
reviewed: 2026-10
---

## Scope

Review guidance for HTTP APIs (REST, JSON-RPC, GraphQL-backed endpoints, and internal services exposed to clients). Use it alongside `owasp-top10.md`. The API list is the current 2023 edition; verify whether a newer revision has been published before citing it as the latest.

## Rules

### SEC-API-001 — API1:2023 Broken Object Level Authorisation (BOLA)

- **Look for:** handlers that load a record by an identifier from the path, query, or body and return it without checking that the caller owns it or has access; list endpoints that filter by a client-supplied tenant or owner id.
- **Why it matters:** the most common API flaw. Any authenticated user can read or change other users' objects by changing an id.
- **Evidence:** the route, the id source, the repository call, and the absent ownership check.
- **Bad:** `repo.findById(id)` returned directly.
- **Good:** `repo.findByIdAndOwnerId(id, principal.getId())` or an explicit policy check.
- **Default severity:** critical for personal or financial data; high otherwise.
- **CWE:** CWE-639, CWE-862, CWE-863.

### SEC-API-002 — API2:2023 Broken Authentication

- **Look for:** endpoints that accept unauthenticated requests where authentication is expected; token validation that does not check signature, issuer, audience, or expiry; API keys in query strings or logs; credential endpoints without rate limits.
- **Detail:** `authn-session.md`.
- **Default severity:** critical when auth is bypassed; high otherwise.
- **CWE:** CWE-287, CWE-306, CWE-798.

### SEC-API-003 — API3:2023 Broken Object Property Level Authorisation

- **Look for:** responses that serialise entire entities, exposing internal or sensitive fields (password hashes, internal flags, other users' data); request bodies bound directly to entities, allowing mass assignment of privileged fields (role, isAdmin, ownerId, price).
- **Good:** separate request and response DTOs with an explicit field list; ignore unknown properties only with a documented policy.
- **Evidence:** the DTO or entity, the field, and the handler that binds or returns it.
- **Default severity:** high when privileged fields are writable; medium for exposure of non-secret internal fields.
- **CWE:** CWE-213, CWE-915, CWE-639.

### SEC-API-004 — API4:2023 Unrestricted Resource Consumption

- **Look for:** no maximum page size; no limit on request body size, file size, array length, or GraphQL depth and complexity; expensive operations (exports, reports, search) with no rate limit; no timeouts on outbound calls.
- **Why it matters:** denial of service and cost exhaustion.
- **Evidence:** the parameter with no bound and the operation it drives.
- **Default severity:** medium; high for unauthenticated endpoints.
- **CWE:** CWE-770, CWE-400, CWE-799.

### SEC-API-005 — API5:2023 Broken Function Level Authorisation (BFLA)

- **Look for:** administrative or privileged endpoints reachable by ordinary roles; HTTP method-based access rules where `PUT` or `DELETE` bypass a check applied only to `GET`; inconsistent role checks across versions of the same endpoint.
- **Evidence:** the endpoint, the required role, and the missing or inconsistent check.
- **Default severity:** critical for administrative functions; high otherwise.
- **CWE:** CWE-285, CWE-862.

### SEC-API-006 — API6:2023 Unrestricted Access to Sensitive Business Flows

- **Look for:** flows that can be automated to abuse business logic (account creation, purchase, coupon redemption, password reset, inventory holds) without bot protection, rate limits, or step-up checks.
- **Evidence:** the flow, the automatable action, and the missing control.
- **Default severity:** medium; high for payment or account takeover flows.
- **CWE:** CWE-799, CWE-841.

### SEC-API-007 — API7:2023 Server-Side Request Forgery

- **Look for:** API fields or parameters that accept URLs and are fetched by the server (webhooks, imports, image URLs, PDF generators); redirects followed without checks.
- **Detail:** `ssrf-path-traversal.md`.
- **Default severity:** high; critical when the fetch reaches cloud metadata or internal admin interfaces.
- **CWE:** CWE-918.

### SEC-API-008 — API8:2023 Security Misconfiguration

- **Look for:** CORS with wildcard origins and credentials; missing security headers; verbose errors and stack traces; unnecessary HTTP methods enabled; TLS not enforced; outdated framework defaults; API documentation or debug routes exposed in production.
- **Detail:** `owasp-top10.md` A02; `java.md` for Spring Actuator; `node-react.md` for Express.
- **Default severity:** medium; high for exposed debug or admin routes.
- **CWE:** CWE-16, CWE-942, CWE-209.

### SEC-API-009 — API9:2023 Improper Inventory Management

- **Look for:** deprecated API versions still routed and unmonitored; undocumented endpoints; staging or internal paths exposed on the public gateway; changes to an endpoint's auth that skip the documentation or contract.
- **Why it matters:** old versions often lack current controls.
- **Evidence:** the route table or gateway config and the version or environment it serves.
- **Default severity:** medium.
- **CWE:** CWE-1059 (documentation) and deployment configuration.

### SEC-API-010 — API10:2023 Unsafe Consumption of APIs

- **Look for:** data from third-party or upstream APIs trusted without validation; upstream redirects followed; TLS validation disabled for upstream calls; upstream error bodies returned to clients unfiltered.
- **Why it matters:** an upstream compromise or misbehaviour propagates to this system.
- **Evidence:** the upstream call, the trust placed in its response, and the sink.
- **Default severity:** high when the response drives authorisation, queries, or code; medium otherwise.
- **CWE:** CWE-20, CWE-295, CWE-345.

## How to apply in review

1. For each changed endpoint, state the principal, the object, and the action. Check BOLA and BFLA first.
2. Compare request and response DTOs with the entity for BOPLA.
3. Check every new parameter for a bound.
4. Cite the route, handler, and missing check by file and line.
5. If the OpenAPI or contract file changed, compare old and new operations.
