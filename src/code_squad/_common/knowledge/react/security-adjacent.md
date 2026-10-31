---
title: Security-adjacent React patterns
source: OWASP Cross Site Scripting Prevention Cheat Sheet; OWASP DOM-based XSS Prevention Cheat Sheet; OWASP HTML5 Security Cheat Sheet; react.dev (dangerouslySetInnerHTML)
version: React 19.2; OWASP cheat sheets (current web versions)
reviewed: 2026-10
---

## Scope

Front-end security issues that a React reviewer will meet in component code. This file is the React-side view. The full security review belongs to `dwight` and the `security` pack; cite `SEC-*` identifiers for depth. Report only issues visible in the diff or directly reachable from it.

## Rules

### REACT-SEC-001 — Unsanitised HTML rendering

- **Look for:** `dangerouslySetInnerHTML` with a value that is not a constant or a sanitised string; `innerHTML`, `outerHTML`, `insertAdjacentHTML`, or `document.write` in effects or refs; markdown rendering without sanitisation.
- **Why it matters:** DOM-based and stored cross-site scripting (CWE-79). Script runs with the user's session.
- **Evidence:** the source of the value (API, URL, user input) and the sink.
- **Bad:** `<div dangerouslySetInnerHTML={{ __html: comment.body }} />`
- **Good:** render as text, or sanitise with a vetted library (for example DOMPurify) using a strict allowlist, then render.
- **Default severity:** high.

### REACT-SEC-002 — User-controlled URLs

- **Look for:** `href`, `src`, `formAction`, or `window.location` set from user input or API data without protocol checks; `javascript:` or `data:` URLs accepted.
- **Why it matters:** `javascript:` URLs execute script on click (CWE-79). Open redirects (CWE-601) enable phishing.
- **Evidence:** the URL source and the sink.
- **Good:** allow only `https:`, `http:`, `mailto:` for links; validate relative paths against an allowlist for redirects.
- **Default severity:** high for `javascript:` sinks; medium for open redirect.

### REACT-SEC-003 — postMessage without origin checks

- **Look for:** `window.addEventListener('message', ...)` handlers that do not check `event.origin`, or that trust `event.data` without validation; `postMessage(data, '*')` carrying sensitive data.
- **Why it matters:** any window can send messages. Unvalidated data drives application behaviour (CWE-346, CWE-345).
- **Evidence:** the listener, the missing origin check, and what the handler does with the data.
- **Default severity:** high.

### REACT-SEC-004 — Tokens in web storage

- **Look for:** access or refresh tokens written to `localStorage` or `sessionStorage`; tokens placed in Redux or global stores that are persisted.
- **Why it matters:** any XSS can read the token (CWE-922, CWE-1004 for missing HttpOnly). Prefer HttpOnly, Secure, SameSite cookies managed by the backend.
- **Evidence:** the storage write and the token variable.
- **Note:** this is a design trade-off. Report it with medium confidence and state the XSS dependency.
- **Default severity:** medium; high for long-lived refresh tokens.

### REACT-SEC-005 — Secrets in the client bundle

- **Look for:** environment variables with `VITE_`, `NEXT_PUBLIC_`, `REACT_APP_`, or equivalent prefixes that contain secrets; API keys hard-coded in source; `.env` files committed with real values.
- **Why it matters:** anything in the bundle is public (CWE-540, CWE-798).
- **Evidence:** the variable name and its usage; the bundle exposure is by design of the prefix.
- **Default severity:** high. Report the location only; never print the value (see `secrets-logging`).

### REACT-SEC-006 — Dynamic code execution

- **Look for:** `eval`, `new Function`, `setTimeout` or `setInterval` with string arguments, dynamic `import()` with user-controlled paths, and template compilation from untrusted input.
- **Why it matters:** code injection (CWE-94, CWE-95).
- **Default severity:** high when input is user-controlled; medium otherwise.

### REACT-SEC-007 — Client-side authorisation is display only

- **Look for:** route guards or UI conditions that hide admin features, with no server-side check; roles read from the client and used to enable actions.
- **Why it matters:** hiding a button does not protect the endpoint (CWE-602, CWE-285).
- **Default severity:** high when the server endpoint lacks the check.

### REACT-SEC-008 — Third-party scripts and iframes

- **Look for:** `<iframe>` without `sandbox` for untrusted content; third-party script tags added without integrity attributes or a content security policy change; `target="_blank"` links without `rel="noopener noreferrer"` (modern browsers imply noopener, but flag explicit legacy targets).
- **Default severity:** low to medium.

### REACT-SEC-009 — Sensitive data in logs and analytics

- **Look for:** `console.log` of tokens, personal data, or full API responses; analytics events containing free-text inputs or email addresses.
- **Why it matters:** logs and analytics are shared more widely than the application data (CWE-532, CWE-359).
- **Default severity:** medium.

## How to apply in review

1. Trace each user-controlled or API-supplied value to its DOM or navigation sink.
2. Check for each sink in the list above, using grep on the changed files first.
3. State the source, the sink, and the attack path. Do not report a sink with a constant argument.
4. For server-side enforcement questions, cite the endpoint and state that it was not inspected if it was not in the diff.
5. Route depth to `dwight` with the matching `SEC-*` identifier.
