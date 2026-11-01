---
title: Component design and composition
source: react.dev (Thinking in React, Passing Props to a Component, Reusing Logic with Custom Hooks, Your First Component)
version: React 19.2
reviewed: 2026-10
---

## Scope

Component boundaries, props design, composition, custom hooks, and component identity. Applies to new components and to changes that alter component APIs. Judge against the project's existing patterns first; generic preference yields to local convention.

## Rules

### REACT-COMP-001 — One clear responsibility per component

- **Look for:** components that fetch data, manage several unrelated states, format output, and handle layout in one function; long components where a reader cannot state the purpose in one sentence.
- **Why it matters:** hard to test, reuse, and change safely.
- **Evidence:** the mixed responsibilities listed by line range. Do not use line count alone as evidence.
- **Default severity:** low to medium.

### REACT-COMP-002 — Compose instead of boolean prop explosion

- **Look for:** components with many mutually exclusive boolean props (`isPrimary`, `isSmall`, `isDanger`, `isOutlined`) or props that change layout drastically.
- **Why it matters:** combinations become invalid and undocumented.
- **Bad:** `<Card isWide isCollapsible showHeader headerRight={...} footerOnly />`
- **Good:** a `variant` union prop, or slots: `<Card><Card.Header>...</Card.Header></Card>`.
- **Default severity:** low.

### REACT-COMP-003 — Components are not defined inside components

- **Look for:** `function Outer() { function Inner() {...} return <Inner/> }` or arrow components declared in the render body.
- **Why it matters:** each render creates a new component type. React unmounts and remounts the subtree, losing state and focus.
- **Evidence:** the nested declaration and the state or focus it loses.
- **Default severity:** high when state or focus is lost; medium otherwise.

### REACT-COMP-004 — Props are minimal and stable

- **Look for:** passing an entire object (`user`) when one field is used; props that change identity every render (inline object or array literals) passed to memoised children; callbacks recreated needlessly. Only raise the memo case if a memoised child exists.
- **Default severity:** low.

### REACT-COMP-005 — Custom hooks encapsulate reusable logic

- **Look for:** the same effect-and-state block copied across components; custom hooks named without `use`; hooks that return unstable shapes without reason.
- **Why it matters:** duplicated logic drifts.
- **Good:** `function useDebouncedValue<T>(value: T, ms: number): T`.
- **Default severity:** low.

### REACT-COMP-006 — Children and render props are typed and purposeful

- **Look for:** `children` typed as `any`; render props that replace a simple prop with no added flexibility; higher-order components added where a hook would work.
- **Default severity:** low.

### REACT-COMP-007 — Keys and identity for stateful children

- **Look for:** a stateful child that must reset when an id changes but lacks `key={id}`; the opposite, where a key forces unnecessary remounts of expensive subtrees.
- **Why it matters:** stale state after navigation between records, or costly remounts.
- **Default severity:** medium.

### REACT-COMP-008 — Public component API is intentional

- **Look for:** internal components exported from a shared module; new exports that expand the public surface without need; breaking prop renames in shared components without a migration.
- **Default severity:** low to medium; medium for shared design-system components.

## How to apply in review

1. Read two or three neighbouring components to learn local conventions.
2. Prefer findings that cause lost state, wrong data, or breakage over stylistic refactors.
3. For API changes to shared components, list the callers affected (search the repo).
4. Cite the component name, file, and line.
5. Do not request extraction into a custom hook for code used once.
