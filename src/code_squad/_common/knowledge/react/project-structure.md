---
title: Project structure and module boundaries
source: react.dev (Thinking in React); Feature-Sliced Design documentation (as one reference model); ESLint import plugin documentation
version: React 19.2; Vite and Next.js conventions as applicable
reviewed: 2026-10
---

## Scope

Folder layout, module boundaries, import direction, shared code, and naming for React applications. The project's own structure is authoritative. Use this file to catch boundary violations and dependency cycles, not to impose a layout on an existing codebase.

## Rules

### REACT-STRUCT-001 — Follow the existing layout

- **Look for:** new files placed in directories that contradict the established pattern (feature folders in a flat `components/` project, or the reverse); new top-level folders without a reason.
- **Why it matters:** discoverability and consistency.
- **Evidence:** two or three existing feature directories and the new file's location.
- **Default severity:** low.

### REACT-STRUCT-002 — No reaching into another module's internals

- **Look for:** imports from `features/billing/components/InvoiceRow` by another feature when the feature exposes an index; deep imports that bypass a documented public API.
- **Why it matters:** internals become a de facto API and block refactoring.
- **Evidence:** the import path and the module's public entry point.
- **Default severity:** low to medium; medium when enforced by project lint rules.

### REACT-STRUCT-003 — No circular imports

- **Look for:** modules that import each other directly or through barrels; components importing from a page that imports them.
- **Why it matters:** undefined values at load time, build warnings, and fragile refactors.
- **Evidence:** the cycle, shown as a chain of imports. Use `madge` or `eslint-plugin-import` `no-cycle` output when available.
- **Default severity:** medium.

### REACT-STRUCT-004 — Shared code has an owner and a reason

- **Look for:** a `utils` or `helpers` file growing without a theme; feature-specific code moved to `shared/` for a single caller; shared code importing from features.
- **Why it matters:** shared modules accumulate unrelated dependencies and become difficult to change.
- **Evidence:** the number of callers and the imports the shared module pulls in.
- **Default severity:** low.

### REACT-STRUCT-005 — Barrel files are used with care

- **Look for:** `index.ts` re-exporting an entire large folder used by components that need one symbol; barrels in libraries that break tree shaking.
- **Why it matters:** bundle size and cycle risk. See `rendering-performance` REACT-PERF-005.
- **Default severity:** low.

### REACT-STRUCT-006 — Naming is consistent

- **Look for:** components in files with different names; hooks without `use`; test files not following the project's convention (`*.test.tsx` versus `__tests__`); route files that do not match route names.
- **Default severity:** low.

### REACT-STRUCT-007 — Environment and configuration are centralised

- **Look for:** `process.env` or `import.meta.env` reads scattered across components; configuration constants duplicated across files.
- **Why it matters:** missing or inconsistent configuration, and secrets reaching the client by accident (see `security-adjacent` REACT-SEC-005).
- **Default severity:** low to medium.

### REACT-STRUCT-008 — Generated code is not hand-edited

- **Look for:** manual edits to generated API clients, route trees, or GraphQL types; generated folders committed without a regeneration step.
- **Default severity:** medium.

## How to apply in review

1. Compare the new file path with the repository's existing features before commenting.
2. Check import direction: UI depends on domain and shared code, not the reverse.
3. For cycles, show the chain and the tool output.
4. Prefer conventions in the repository over this file's examples.
5. Keep structure findings low severity unless they cause a functional or security problem.
