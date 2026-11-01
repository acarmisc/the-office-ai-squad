---
title: Node.js and React security patterns
source: OWASP Prototype Pollution Prevention Cheat Sheet; OWASP DOM-based XSS Prevention Cheat Sheet; OWASP NodeJS Security Cheat Sheet; React documentation (dangerouslySetInnerHTML); MDN (postMessage, Web Storage); npm documentation (lifecycle scripts)
version: Node.js 22 LTS and 24 LTS (verify engines field); React 19.2; npm 10+
reviewed: 2026-10
---

## Scope

Security issues specific to JavaScript and TypeScript on the server (Node.js, Express-style frameworks, Next.js route handlers) and in the browser (React). Pair with `xss-csrf.md`, `injection.md`, and `ssrf-path-traversal.md` for the general classes. The React-side code-quality view is in the `react` pack (`security-adjacent.md`); this file is the security authority for these patterns.

## Rules

### SEC-NODE-001 — Prototype pollution

- **Look for:** recursive merge, deep clone, or `set` utilities that copy keys from input objects without filtering `__proto__`, `constructor`, and `prototype`; `Object.assign` or spread into objects built from `req.body`; `obj[key] = value` where `key` comes from input.
- **Why it matters:** attacker input modifies `Object.prototype`, changing behaviour across the process (CWE-1321).
- **Bad:** `function merge(t, s) { for (const k in s) { t[k] = typeof s[k] === 'object' ? merge(t[k] || {}, s[k]) : s[k]; } return t; }`
- **Good:** skip the three dangerous keys; use `Object.create(null)` for dictionaries, or `Map`; use a maintained merge library version that addresses the issue.
- **Default severity:** high; critical when the polluted property reaches an authorisation check, command, or template.

### SEC-NODE-002 — Mass assignment from request bodies

- **Look for:** `Model.create(req.body)`, `Object.assign(entity, req.body)`, `prisma.user.update({ data: req.body })`, spreading request objects into database writes.
- **Why it matters:** clients set privileged fields (role, isAdmin, ownerId, price) (CWE-915).
- **Good:** pick the allowed fields explicitly; validate with a schema that rejects unknown keys.
- **Default severity:** high when privileged fields are writable.

### SEC-NODE-003 — Command execution

- **Look for:** `child_process.exec` and `execSync` with template strings; `spawn` with `shell: true`; calls to tools with user-controlled arguments.
- **Good:** `execFile` or `spawn` with an argument array and no shell; validate arguments. See `injection.md` SEC-INJECT-005.
- **Default severity:** critical when reachable.
- **CWE:** CWE-78, CWE-77.

### SEC-NODE-004 — Dynamic code execution

- **Look for:** `eval`, `new Function`, `vm.runInNewContext` (not a security sandbox), `setTimeout(string)`, template engines compiling input, `require` with a path from input.
- **Why it matters:** `vm` is not a security boundary. Node's `vm` module documents this explicitly.
- **Default severity:** critical when input reaches evaluation.
- **CWE:** CWE-94, CWE-95.

### SEC-NODE-005 — Regular expression denial of service

- **Look for:** regular expressions with nested quantifiers or overlapping alternation applied to user input (`(a+)+`, `(\s*\w+)*`); validation regexes on unbounded input.
- **Good:** bound input length before matching; use linear-time engines or safe patterns; test with long adversarial input.
- **Default severity:** medium to high on request paths.
- **CWE:** CWE-1333, CWE-400.

### SEC-NODE-006 — Express and HTTP server configuration

- **Look for:** `app.use(express.static(dir))` with user paths; `trust proxy` set to `true` (trusts all `X-Forwarded-*`); `x-powered-by` enabled; missing `helmet` or equivalent headers in public apps; body parser limits absent.
- **Good:** `trust proxy` set to the number of hops; set body size limits; set security headers.
- **Default severity:** medium; high where IP-based controls depend on `X-Forwarded-For`.
- **CWE:** CWE-348, CWE-16.

### SEC-NODE-007 — CORS configuration

- **Look for:** `origin: true` or reflected `Origin` with `credentials: true`; `origin: '*'` with credentials (invalid, indicates misunderstanding); allowed headers including sensitive custom headers without need.
- **Default severity:** high when credentials are allowed for reflected origins.
- **CWE:** CWE-942.

### SEC-NODE-008 — Cookies and sessions

- **Look for:** `cookie-session` or `express-session` with a weak or default secret; cookies without `httpOnly`, `secure`, `sameSite`; session stores in memory in production.
- **Default severity:** high for default secrets.
- **CWE:** CWE-1188, CWE-614, CWE-1004.

### SEC-NODE-009 — npm install and lifecycle scripts

- **Look for:** new or updated packages with `preinstall`, `install`, or `postinstall` scripts; CI commands without `--ignore-scripts` for untrusted dependency trees; `prepare` scripts downloading binaries; `npx` of unpinned packages in CI.
- **Why it matters:** lifecycle scripts run with the installer's privileges and may read environment secrets.
- **Good:** `npm ci --ignore-scripts`, then run allowlisted rebuilds; pin `npx` packages to exact versions; isolate install in CI from secrets where possible.
- **Default severity:** high when scripts download code or read credentials.
- **Detail:** `supply-chain-ssdf-slsa.md` SEC-SUPPLY-003.

### SEC-NODE-010 — Secrets and environment variables

- **Look for:** `process.env` values logged or returned to clients; `.env` files committed; environment dumps in error handlers; `NEXT_PUBLIC_`, `VITE_`, or `REACT_APP_` variables containing secrets.
- **Default severity:** high. Report location only.
- **Detail:** `secrets-logging.md`, `react` pack REACT-SEC-005.

### SEC-NODE-011 — JWT handling in Node

- **Look for:** `jwt.decode` used as verification; `jsonwebtoken` `verify` called without `algorithms`; `ignoreExpiration: true`; secrets shorter than required.
- **Detail:** `authn-session.md` SEC-AUTHN-009.
- **Default severity:** critical when verification is bypassed.

### SEC-NODE-012 — Unsafe deserialisation in Node

- **Look for:** `node-serialize` or `serialize-javascript` used on input; `JSON.parse` with a reviver that constructs objects; YAML loaded with unsafe schema (`js-yaml` `load` with custom types).
- **Default severity:** critical for untrusted input with code-capable deserialisers.
- **Detail:** `deserialisation.md`.

### SEC-NODE-013 — Browser: dangerouslySetInnerHTML and HTML sinks

- **Look for:** `dangerouslySetInnerHTML={{ __html: x }}` where `x` is not constant or sanitised; `innerHTML`, `document.write`, and `insertAdjacentHTML` with input.
- **Good:** render text; sanitise with DOMPurify under a strict allowlist when HTML is required.
- **Default severity:** high.
- **Detail:** `xss-csrf.md` SEC-XSS-001 and SEC-XSS-004.

### SEC-NODE-014 — Browser: postMessage

- **Look for:** `message` listeners that do not check `event.origin` against an allowlist; handlers that use `event.data` as code, HTML, or a URL; `postMessage(payload, '*')` with sensitive payloads.
- **Good:** check origin exactly, check `event.source` where relevant, validate the message schema, and send to a specific target origin.
- **Default severity:** high.
- **CWE:** CWE-345, CWE-346.

### SEC-NODE-015 — Browser: tokens in web storage

- **Look for:** access or refresh tokens written to `localStorage` or `sessionStorage`; tokens exposed to third-party scripts through globals.
- **Why it matters:** any XSS reads the token. Prefer HttpOnly, Secure, SameSite cookies set by the server, with CSRF protection for cookie-authenticated requests.
- **Note:** a trade-off with its own risks; report with medium confidence where the architecture requires client tokens.
- **Default severity:** medium; high for long-lived refresh tokens.
- **CWE:** CWE-922, CWE-1004.

### SEC-NODE-016 — Browser: URL and redirect sinks

- **Look for:** `window.location` or `href` assigned from query strings or fragments; open redirects after login using `returnUrl` without allowlist.
- **Default severity:** medium to high.
- **CWE:** CWE-601, CWE-79.

### SEC-NODE-017 — Next.js and server actions

- **Look for:** `'use server'` actions and route handlers that trust input and skip authorisation; server-only modules imported into client components; caching of per-user responses without per-user keys.
- **Good:** validate and authorise inside each action; mark server-only modules.
- **Default severity:** high.
- **Detail:** `react` pack REACT-RSC-002, REACT-RSC-004, REACT-RSC-005.

### SEC-NODE-018 — Browser: third-party iframes and frame embedding

- **Look for:** pages with sensitive actions that can be framed (no `frame-ancestors` or `X-Frame-Options`); iframes loading untrusted content without `sandbox`.
- **Default severity:** medium.
- **CWE:** CWE-1021.

## How to apply in review

1. Identify the runtime (server, browser, or both) for each changed file.
2. Check merge, assign, and deserialisation calls for input-controlled keys and types.
3. Check each browser sink and each message listener.
4. For configuration, check Express or framework settings in the diff, and check the environment variables they read.
5. Cite the file and line, and the rule id. Use `dependency-triage.md` for package-level questions.
