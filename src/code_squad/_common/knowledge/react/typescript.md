---
title: TypeScript in React code
source: TypeScript Handbook (Narrowing, Type Guards, strict mode); react.dev (TypeScript usage); typescript-eslint recommended rules
version: TypeScript 5.x with @types/react 19
reviewed: 2026-10
---

## Scope

Type safety in React components, hooks, props, state, event handlers, and API boundaries. Applies to `.ts` and `.tsx` files. Check `tsconfig.json` for `strict` before judging type findings: a loose config changes severity.

## Rules

### REACT-TS-001 — No `any` leakage

- **Look for:** explicit `any`, implicit `any` through untyped parameters (`noImplicitAny` disabled), `as any` casts, and `// @ts-ignore` or `@ts-expect-error` without a reason.
- **Why it matters:** `any` disables checking for everything it touches, including callers.
- **Evidence:** the line, the type, and a caller whose type error is now hidden.
- **Bad:** `function parse(x: any) { return x.items.map(...) }`
- **Good:** `function parse(x: unknown): Item[] { /* validate, then narrow */ }`
- **Default severity:** medium; high at a trust boundary (API response, `postMessage`, URL params).

### REACT-TS-002 — Model UI state as discriminated unions

- **Look for:** several booleans (`isLoading`, `isError`, `data?`) that can represent impossible combinations.
- **Why it matters:** impossible states (loading and error at once) become reachable.
- **Bad:** `{ isLoading: boolean; error?: Error; data?: Item }`
- **Good:** `type State = { status: 'idle' } | { status: 'loading' } | { status: 'error'; error: Error } | { status: 'ok'; data: Item }`
- **Default severity:** low to medium.

### REACT-TS-003 — Non-null assertions and casts are justified

- **Look for:** `!` non-null assertions on values that can be null at runtime; `as SomeType` casts that bypass checking; `<T>` casts on DOM queries without a null check.
- **Why it matters:** the compiler stops checking, and a runtime null produces a crash in production.
- **Evidence:** the expression and the condition that makes it non-null (or the absence of one).
- **Default severity:** medium.

### REACT-TS-004 — External data is validated at runtime

- **Look for:** `response.json()` cast to a type, `JSON.parse` results used as typed objects, URL search params or route params trusted by type alone.
- **Why it matters:** TypeScript types are erased at runtime. A changed API silently breaks rendering.
- **Evidence:** the call, the type assertion, and the field accessed without a check.
- **Good:** parse with a schema library (zod, valibot, or the project's equivalent) at the boundary.
- **Default severity:** medium; high when the data drives authorisation or money.

### REACT-TS-005 — Props and event types are precise

- **Look for:** props typed as `object`, `Function`, or `{}`; `any` in event handler parameters; `children` typed incorrectly; `string` where a union of literals describes the allowed values.
- **Why it matters:** callers pass invalid values that the component accepts.
- **Good:** `variant: 'primary' | 'danger'`; `onChange: (e: React.ChangeEvent<HTMLInputElement>) => void`.
- **Default severity:** low.

### REACT-TS-006 — Strict compiler settings are enabled

- **Look for:** `strict: false` in `tsconfig.json`, or new code that adds `// @ts-nocheck` at file level.
- **Why it matters:** many defects in this pack become invisible.
- **Evidence:** the `tsconfig` line. Do not demand a full migration in one change; flag new files that opt out.
- **Default severity:** low to medium.

### REACT-TS-007 — Exhaustiveness on unions

- **Look for:** `switch` on a union without a `default` branch that asserts `never`, where a new member would fall through silently.
- **Why it matters:** adding a variant compiles and misbehaves at runtime.
- **Good:** `default: { const _exhaustive: never = value; throw new Error(...) }`
- **Default severity:** low.

### REACT-TS-008 — Type-only imports and exports where required

- **Look for:** type-only symbols imported without `import type` in projects with `verbatimModuleSyntax` or `isolatedModules` enforcing it; re-exports of types that break bundlers.
- **Why it matters:** build failures or unnecessary runtime imports.
- **Evidence:** the tsconfig setting and the import line.
- **Default severity:** low.

## How to apply in review

1. Read `tsconfig.json` first. Note `strict` and `noImplicitAny`.
2. Focus on boundaries: network responses, route params, storage reads, `postMessage` payloads.
3. Do not flag style-only preferences (type alias versus interface) unless the project's lint config enforces them.
4. For every cast or non-null assertion you report, show the runtime case that breaks it.
5. Prefer narrowing and validation fixes over more casts in the suggested remedy.
