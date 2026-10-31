---
title: React Server Components and Next.js
source: react.dev (Server Components, Server Functions); Next.js App Router documentation
version: React 19.2 with Next.js App Router (verify the Next.js major version in package.json)
reviewed: 2026-10
unverified-edition: true
---

## Scope

Applies only when the project uses React Server Components (RSC), Server Actions, or a framework that embeds them (Next.js App Router, or other RSC-capable frameworks). Detect from `next` in `package.json` and presence of `app/` or `'use server'` / `'use client'` directives. For plain client-side React, skip this file.

Framework caching and routing defaults change between major versions. Always confirm the framework version before citing a default.

## Rules

### REACT-RSC-001 — Client boundary is as small as possible

- **Look for:** `'use client'` at the top of a layout, page, or large shared module when only a leaf needs interactivity; client components importing server-only modules.
- **Why it matters:** everything imported by a client module is shipped to the browser. Large trees marked client lose server rendering benefits.
- **Evidence:** the directive, the file, and the imports that pull in heavy or server-only code.
- **Good:** keep the page on the server; move the interactive button to a small client component.
- **Default severity:** medium.

### REACT-RSC-002 — Secrets and server-only data do not cross into client code

- **Look for:** environment variables without a public prefix read in client modules; database clients or API keys imported into a `'use client'` file; full database rows passed as props when only a few fields are needed.
- **Why it matters:** props serialised across the boundary appear in the HTML payload and are visible to any user.
- **Evidence:** the prop or import and the sensitive field it exposes.
- **Good:** map to a DTO with only display fields; add `import 'server-only'` to modules that must not reach the client.
- **Default severity:** high. Cross-reference `SEC-SECRETS-*` and `SEC-AUTHN-*` in the security pack.

### REACT-RSC-003 — Only serialisable values cross the boundary

- **Look for:** functions, class instances, or non-serialisable objects passed from server to client components as props (other than Server Actions).
- **Why it matters:** the framework rejects these at runtime or silently changes their shape.
- **Evidence:** the prop and its type.
- **Default severity:** medium.

### REACT-RSC-004 — Server Actions validate input and authorise the caller

- **Look for:** `'use server'` functions that trust their arguments, skip authentication, or check only on the client; no schema validation; direct database writes using client-supplied ids.
- **Why it matters:** Server Actions are public HTTP endpoints. Any client can call them with arbitrary input.
- **Evidence:** the action signature, the absent check, and the write it performs.
- **Good:** validate with a schema, check the session and the record's ownership inside the action.
- **Default severity:** high. Cross-reference `SEC-ACCESS-*` (broken access control).

### REACT-RSC-005 — Caching behaviour matches the framework version

- **Look for:** assumptions that `fetch` results are cached or uncached by default without checking the framework version; stale data after mutation without `revalidatePath` or `revalidateTag`; `cache` or `unstable_cache` wrapping per-user data without per-user keys.
- **Why it matters:** caching defaults changed between major versions of Next.js. Per-user data cached globally is a data exposure risk.
- **Evidence:** the framework version, the fetch or cache call, and the cache key.
- **Default severity:** high for per-user data cached globally; medium otherwise.

### REACT-RSC-006 — Request-scoped APIs are used in allowed contexts

- **Look for:** `cookies()`, `headers()`, or `draftMode()` called in contexts where the framework disallows them (for example, inside cached functions); setting cookies from a render path.
- **Why it matters:** the framework throws, or the cookie is set for the wrong request.
- **Evidence:** the call site and its enclosing function.
- **Default severity:** medium.

### REACT-RSC-007 — Client and server share no implicit state

- **Look for:** module-level mutable variables in server code that store per-request data.
- **Why it matters:** server processes handle many requests. Module state leaks between users.
- **Evidence:** the module-level `let` or cache object and the request data written to it.
- **Default severity:** high.

## How to apply in review

1. Confirm the framework and its major version before reviewing caching or routing.
2. Trace each `'use client'` file's imports and check for server-only dependencies.
3. For every Server Action, identify the input, the auth check, and the write.
4. Cite the file and the boundary, not the general framework behaviour.
5. If the project does not use RSC, state that this pack does not apply.
