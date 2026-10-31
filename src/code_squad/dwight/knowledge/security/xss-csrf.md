---
title: Cross-site scripting (XSS) and cross-site request forgery (CSRF)
source: OWASP Cross Site Scripting Prevention Cheat Sheet; OWASP DOM-based XSS Prevention Cheat Sheet; OWASP Cross-Site Request Forgery Prevention Cheat Sheet; MDN (SameSite cookies)
version: OWASP Top 10:2025 A05 (XSS) and A01 (CSRF folded into access control); CWE-79 and CWE-352
reviewed: 2026-10
---

## Scope

Reflected, stored, and DOM-based XSS; and cross-site request forgery for cookie-authenticated state changes. Applies to server-rendered HTML, client-side rendering, and APIs whose responses are rendered in browsers. Framework-specific sinks are in `node-react.md`.

## Rules

### SEC-XSS-001 — Context-correct output encoding

- **Look for:** untrusted data written into HTML bodies, attributes, JavaScript blocks, CSS, or URLs without encoding for that context. Template helpers that disable escaping (`raw`, `|safe`, triple-brace, unescaped output).
- **Why it matters:** script runs in the victim's origin with their session (CWE-79, CWE-80).
- **Evidence:** the template or code line, the data source, and the context.
- **Good:** use the template engine's default escaping; for JavaScript contexts, serialise to JSON with a safe encoder; for URLs, validate the scheme (see SEC-XSS-003).
- **Default severity:** high; critical for stored XSS in admin views or authenticated shared content.

### SEC-XSS-002 — Stored content rendered as HTML

- **Look for:** rich text, comments, names, or markdown stored and rendered as HTML without sanitisation; sanitisers configured with broad allowlists; sanitisation applied at storage time only.
- **Why it matters:** stored payloads affect every viewer.
- **Good:** sanitise on output with a maintained library and a strict allowlist, or render as text.
- **Default severity:** high.

### SEC-XSS-003 — URL schemes in links and sources

- **Look for:** `href`, `src`, or `action` values from user input without scheme validation, allowing `javascript:` or `data:` URLs (`data:text/html` in iframes).
- **Good:** allow only `http`, `https`, and `mailto` for links; reject others.
- **Default severity:** high.

### SEC-XSS-004 — DOM-based XSS

- **Look for:** sinks such as `innerHTML`, `outerHTML`, `document.write`, `insertAdjacentHTML`, `eval`, `setTimeout(string)`, jQuery `.html()`, and assignments to `location` or `src` with values from `location.hash`, `location.search`, `document.referrer`, `postMessage`, or storage.
- **Good:** use `textContent` or DOM APIs for text; validate sources before sinks.
- **Default severity:** high.

### SEC-XSS-005 — Content-Type and MIME sniffing

- **Look for:** user-uploaded content or JSON responses served without `Content-Type` or with a type that browsers render as HTML; missing `X-Content-Type-Options: nosniff`.
- **Good:** set the correct `Content-Type`; set `nosniff`; serve uploads from a separate origin.
- **Default severity:** medium.

### SEC-XSS-006 — Content Security Policy

- **Look for:** absence of CSP on pages with user content; `unsafe-inline` or `unsafe-eval` added to CSP without necessity; wildcard script sources.
- **Why it matters:** CSP is defence in depth. It does not replace encoding.
- **Default severity:** low to medium; medium when inline scripts are required by the code under review.

### SEC-XSS-007 — Reflected input in error and redirect pages

- **Look for:** error messages or pages that echo query parameters; redirect messages that include input unencoded.
- **Default severity:** medium.

### SEC-CSRF-001 — State change requires CSRF protection

- **Look for:** `POST`, `PUT`, `PATCH`, or `DELETE` endpoints that authenticate with cookies and do not require a CSRF token or verify `Origin` and `Referer`; `GET` endpoints that change state.
- **Why it matters:** a third-party site can trigger the action in the victim's browser (CWE-352).
- **Evidence:** the endpoint, the authentication mechanism, and the absence of token or origin validation.
- **Note:** APIs that authenticate only with a bearer token in a header are not exposed to classic CSRF. Confirm how the token is sent before reporting.
- **Default severity:** high for money, account, or permission changes; medium otherwise.

### SEC-CSRF-002 — Cookie attributes

- **Look for:** session cookies without `HttpOnly`, `Secure`, or a `SameSite` attribute (`Lax` or `Strict` for session cookies unless a cross-site flow requires `None`).
- **Why it matters:** `SameSite` reduces cross-site request risk; `HttpOnly` reduces script access (CWE-1004, CWE-614, CWE-1275).
- **Default severity:** medium; high for session cookies without `HttpOnly` or `Secure`.

### SEC-CSRF-003 — Tokens are unpredictable and bound to the session

- **Look for:** CSRF tokens generated from predictable values, reused across users, not rotated on login, or not validated server-side.
- **Default severity:** high when the token is ineffective.

### SEC-CSRF-004 — Login and logout CSRF

- **Look for:** login endpoints without CSRF protection that can be used to log a victim into an attacker's account; logout actions triggered by `GET`.
- **Default severity:** low to medium.

### SEC-CSRF-005 — CORS is not CSRF protection

- **Look for:** reliance on CORS settings to stop cross-site state changes; `Access-Control-Allow-Origin` reflecting any origin with credentials enabled.
- **Why it matters:** CORS controls reading responses, not sending simple requests. Reflecting origins with credentials exposes responses (CWE-942).
- **Default severity:** high when credentials are allowed with reflected or wildcard origins.

## How to apply in review

1. Locate each sink that renders a string into HTML, a URL, or a script.
2. Trace the data back to its origin: request, database, another user, or a third party.
3. For each state-changing endpoint, check the authentication mechanism and the CSRF defence.
4. Cite the file, line, sink, and the context (HTML, attribute, JS, URL).
5. Do not report a template that escapes by default unless the diff disables escaping or inserts raw HTML.
