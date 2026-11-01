---
title: Error handling, error boundaries and Suspense
source: react.dev (Error Boundaries, Suspense, createRoot onCaughtError/onUncaughtError); React 19 upgrade guide
version: React 19.2
reviewed: 2026-10
---

## Scope

Error boundaries, handling of errors that boundaries do not catch, Suspense fallbacks and waterfalls, and what users see on failure. Covers client rendering and framework-level equivalents.

## Rules

### REACT-ERR-001 — Error boundaries wrap independent regions

- **Look for:** no error boundary in an application with several independent features; one global boundary that replaces the whole app for a single failing widget; no boundary around third-party widgets.
- **Why it matters:** one failure takes down unrelated content.
- **Evidence:** the component tree and the boundary placement.
- **Default severity:** medium.

### REACT-ERR-002 — Boundaries do not catch everything

- **Look for:** async errors in `useEffect`, event handlers, `setTimeout`, and promise rejections assumed to reach a boundary. They do not.
- **Why it matters:** errors go unhandled, leave the UI in a loading state forever, or surface as unhandled promise rejections.
- **Evidence:** the async code and the absent `try/catch` or state-based error handling.
- **Good:** catch in the handler, set an error state, or rethrow inside render using the state pattern so a boundary receives it.
- **Default severity:** medium to high.

### REACT-ERR-003 — No swallowed errors

- **Look for:** empty `catch` blocks; `.catch(() => {})`; errors converted to `null` with no logging; generic fallbacks that hide the cause.
- **Why it matters:** failures become invisible to users and to monitoring.
- **Evidence:** the catch block.
- **Default severity:** medium.

### REACT-ERR-004 — Suspense boundaries avoid waterfalls

- **Look for:** sequential `Suspense` boundaries in a parent-child chain that each wait for the previous; data requested in child components after the parent resolves; one boundary around a large tree showing a single spinner.
- **Why it matters:** load time grows with depth. Fallbacks that replace large areas cause layout shift.
- **Evidence:** the boundary nesting and the request sequence in a network trace.
- **Default severity:** medium.

### REACT-ERR-005 — Fallbacks preserve layout

- **Look for:** fallbacks with different dimensions than the loaded content; spinners that replace content the user was reading.
- **Why it matters:** layout shift and lost context.
- **Default severity:** low.

### REACT-ERR-006 — Error UI does not leak internals

- **Look for:** `error.message`, `error.stack`, SQL errors, file paths, or internal ids rendered to end users in production builds; error details sent to third-party services with user data.
- **Why it matters:** information disclosure (CWE-209). Cross-reference `SEC-LOG-*`.
- **Evidence:** the rendered output and the source of the message.
- **Default severity:** medium; high if secrets or tokens can appear in the message.

### REACT-ERR-007 — Boundaries reset on navigation or input change

- **Look for:** an error boundary that stays in error after the user navigates or changes the input, with no reset key or retry.
- **Why it matters:** the user must reload the page to recover.
- **Default severity:** low to medium.

### REACT-ERR-008 — Root error reporting is configured

- **Look for:** `createRoot` options missing where the project relies on error reporting; errors logged twice (boundary and global handler).
- **Why it matters:** React 19 reports caught and uncaught render errors through root callbacks. Duplicate or missing reports make triage harder.
- **Evidence:** the `createRoot` call and the reporting setup.
- **Default severity:** low.

## How to apply in review

1. For each async operation in the diff, trace what happens on failure and who sees it.
2. Check boundary placement against the feature layout.
3. Cite the code path that drops the error or leaks it.
4. Confirm the React version before recommending root error options.
5. Do not require a boundary around every component.
