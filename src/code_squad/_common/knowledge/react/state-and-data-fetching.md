---
title: State placement and data fetching
source: react.dev (Managing State, Reacting to Input with State, Passing Data Deeply with Context); TanStack Query and SWR documentation
version: React 19.2
reviewed: 2026-10
---

## Scope

Where state lives (local, lifted, context, external store, server state), how data is fetched and cached, and how optimistic updates are applied. Applies to client-side React applications and to client components in frameworks.

## Rules

### REACT-STATE-001 — State lives at the lowest common owner

- **Look for:** state declared high in the tree but read by one child; state duplicated in parent and child; several sources of truth for one value.
- **Why it matters:** unnecessary re-renders and state that drifts out of sync.
- **Evidence:** the state variable, its reads, and its writers. Name the single owner you recommend.
- **Default severity:** low to medium.

### REACT-STATE-002 — Do not copy props into state

- **Look for:** `useState(props.x)` where `x` is expected to change over time, with no key-based reset and no sync logic.
- **Why it matters:** the state is initialised once and ignores later prop changes.
- **Evidence:** the `useState` initialiser reading a prop and the parent that changes that prop.
- **Good:** derive the value, or reset the child with `key={id}`.
- **Default severity:** medium.

### REACT-STATE-003 — Server state uses a data-fetching layer

- **Look for:** hand-rolled `useEffect` + `useState` fetch logic repeated across components; no cache, deduplication, retry, or invalidation; manual loading and error flags in many places.
- **Why it matters:** inconsistent caching, duplicated requests, and stale data after mutations. Libraries such as TanStack Query, SWR, RTK Query, or framework loaders handle these concerns.
- **Evidence:** the number of duplicated fetch sites and the absence of invalidation after a mutation.
- **Note:** do not demand a library where the project has one routine fetch. Judge by repetition and by the cost of stale data.
- **Default severity:** low to medium; medium when mutations leave visible stale data.

### REACT-STATE-004 — Context is not a high-frequency store

- **Look for:** one context value that bundles many fields updated at different rates (for example, a `theme` and a `cursorPosition` in one provider); large objects created inline in the provider value.
- **Why it matters:** every consumer re-renders whenever any part of the value changes.
- **Evidence:** the provider `value` prop, its update frequency, and consumers that need only one field.
- **Bad:** `<Ctx.Provider value={{ user, cart, ui }}>` with a new object each render.
- **Good:** split into `UserCtx`, `CartCtx`; memoise the value only when profiling shows cost.
- **Default severity:** medium.

### REACT-STATE-005 — Shared client state uses a store with selectors

- **Look for:** a global store subscription that returns the whole state object; selectors that create new objects or arrays each call; unrelated slices read together.
- **Why it matters:** re-render storms. Selectors returning new references defeat equality checks.
- **Evidence:** the selector and what it returns; whether it returns a stable reference.
- **Default severity:** medium.

### REACT-STATE-006 — Optimistic updates have a rollback path

- **Look for:** optimistic UI updates with no error handling that restores the previous value, or no reconciliation after the server response.
- **Why it matters:** the UI shows success for a change that failed on the server.
- **Evidence:** the optimistic write, the failure branch, and the missing rollback.
- **Default severity:** medium; high for financial or permission-related data.

### REACT-STATE-007 — Query keys include every input

- **Look for:** cached queries whose key omits a parameter the request depends on (tenant id, locale, filter).
- **Why it matters:** users receive another tenant's or filter's data from cache. This is also a data-exposure risk (see `security-adjacent`).
- **Evidence:** the request function's parameters and the key array.
- **Default severity:** high when data is tenant- or user-scoped; medium otherwise.

### REACT-STATE-008 — Mutations invalidate or update related queries

- **Look for:** create, update, or delete calls that do not refresh the lists or details that display the changed record.
- **Why it matters:** the user sees stale data after a successful action.
- **Evidence:** the mutation and the query keys it should invalidate.
- **Default severity:** low to medium.

## How to apply in review

1. Identify the data source for each piece of state: UI-only, server, URL, or derived.
2. Check that server data has one fetch path and an invalidation story.
3. For context and store changes, check which consumers re-render and why.
4. Cite the component, the state or fetch call, and the observable symptom (stale data, extra renders, wrong tenant data).
5. If the project already uses a data library, enforce its conventions over generic advice.
