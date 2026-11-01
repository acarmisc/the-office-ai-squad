---
title: Hooks and effects
source: react.dev (Synchronizing with Effects, Rules of Hooks, You Might Not Need an Effect); eslint-plugin-react-hooks
version: React 19.2
reviewed: 2026-10
---

## Scope

Review of `useState`, `useEffect`, `useLayoutEffect`, `useRef`, `useMemo`, `useCallback`, `useEffectEvent`, and custom hooks. Effects synchronise a component with an external system (network, DOM API, subscription, timer). Most other "effects" are better expressed as render logic or event handlers.

## Rules

### REACT-HOOKS-001 — Rules of Hooks

- **Look for:** hooks called conditionally, inside loops, after an early `return`, inside callbacks, or from non-component/non-hook functions. Hook names not prefixed with `use` when they call hooks.
- **Why it matters:** React relies on call order to associate state with hooks. Violations corrupt state silently or throw at runtime.
- **Evidence:** the offending line and the early return or condition above it. `eslint-plugin-react-hooks` `rules-of-hooks` output.
- **Bad:** `if (open) { const [x] = useState(0); }`
- **Good:** `const [x] = useState(0); if (!open) return null;`
- **Default severity:** high.

### REACT-HOOKS-002 — Effect dependencies are complete

- **Look for:** `useEffect`/`useMemo`/`useCallback` dependency arrays that omit values read inside the callback; `// eslint-disable-next-line react-hooks/exhaustive-deps` without a justification comment; dependency arrays that include unstable objects or functions created on every render.
- **Why it matters:** missing dependencies cause stale closures (the effect keeps using old props or state). Suppressing the lint rule hides the defect.
- **Evidence:** the variable read in the body, missing from the array, and the render cycle in which it goes stale.
- **Bad:** `useEffect(() => { save(draft); }, []);` (where `draft` changes)
- **Good:** `useEffect(() => { save(draft); }, [draft, save]);` with `save` stabilised if needed.
- **Default severity:** medium; high when stale data drives a write, payment, or authorisation decision.

### REACT-HOOKS-003 — No effect for derived state

- **Look for:** `useEffect` whose only job is `setX(f(y))` after a prop or state change; state that duplicates a value computable from other state.
- **Why it matters:** an extra render pass, a visible flash of stale UI, and a second source of truth that can drift.
- **Evidence:** the effect body and the state it sets; show that the value can be computed during render.
- **Bad:**
  ```tsx
  const [full, setFull] = useState('');
  useEffect(() => setFull(`${first} ${last}`), [first, last]);
  ```
- **Good:**
  ```tsx
  const full = `${first} ${last}`;
  ```
- **Default severity:** medium.

### REACT-HOOKS-004 — Fetch effects handle races and cleanup

- **Look for:** `fetch` or async calls in `useEffect` that call `setState` without an `ignore` flag or `AbortController`; missing error handling; unmount after resolve producing state updates.
- **Why it matters:** responses for an earlier input can overwrite a newer result. Users see data for the wrong record.
- **Evidence:** the async call, the state setter, and the absence of cancellation.
- **Bad:**
  ```tsx
  useEffect(() => { fetch(`/api/items/${id}`).then(r => r.json()).then(setItem); }, [id]);
  ```
- **Good:**
  ```tsx
  useEffect(() => {
    const ac = new AbortController();
    fetch(`/api/items/${id}`, { signal: ac.signal })
      .then(r => r.json()).then(setItem)
      .catch(e => { if (e.name !== 'AbortError') setError(e); });
    return () => ac.abort();
  }, [id]);
  ```
  Prefer a server-state library (see `state-and-data-fetching`).
- **Default severity:** high.

### REACT-HOOKS-005 — Subscriptions and timers are cleaned up

- **Look for:** `addEventListener`, `setInterval`, `setTimeout`, WebSocket, observers, or third-party `on()` subscriptions in an effect without a returned cleanup.
- **Why it matters:** leaks, duplicate handlers after remount, callbacks firing on unmounted components.
- **Evidence:** the registration call and the missing matching teardown.
- **Default severity:** medium.

### REACT-HOOKS-006 — Event logic belongs in event handlers

- **Look for:** effects that run because a user did something (`useEffect` watching a `submitted` flag that a click set), causing an extra render and effect run.
- **Why it matters:** the effect runs on mount and on any dependency change, not only on the intended action. Side effects become hard to reason about.
- **Evidence:** the state flag set in a handler and consumed by an effect.
- **Good:** call the side effect directly in `onClick`.
- **Default severity:** low to medium.

### REACT-HOOKS-007 — Refs are not read or written during render

- **Look for:** `ref.current` read or assigned in the render body (other than lazy initialisation patterns the project documents); `useRef` used to store values that should be state.
- **Why it matters:** render must be pure. Reads during render produce results that differ between runs under concurrent rendering and Strict Mode.
- **Evidence:** the line with `.current` in the component body, outside an event handler or effect.
- **Default severity:** medium.

### REACT-HOOKS-008 — Effects are idempotent under Strict Mode

- **Look for:** effects that create non-idempotent external resources (for example, registering the same analytics event or socket twice without teardown) that break when React mounts, unmounts, and remounts in development.
- **Why it matters:** Strict Mode double-invokes effects in development to surface missing cleanup. Non-idempotent effects behave differently in development and production.
- **Evidence:** the effect and the resource it creates; whether cleanup reverses it.
- **Default severity:** medium.

### REACT-HOOKS-009 — useEffectEvent and new hook APIs are version-gated

- **Look for:** `useEffectEvent` (shipped in React 19.2) or other newer APIs used in a project whose React version or lint plugin does not support them.
- **Why it matters:** the code fails at build time or is silently undefined at runtime.
- **Evidence:** the `react` version in `package.json` or lockfile versus the API used.
- **Default severity:** medium (build break) to high (runtime undefined).

## How to apply in review

1. Confirm the React version from `package.json` and the lockfile before citing a hook API.
2. Run the question "can this value be computed during render?" on every effect that sets state.
3. For each effect, identify the external system it synchronises with and check the teardown.
4. Check that `eslint-disable` for `exhaustive-deps` has a reason.
5. Cite the file, line, and the render or event sequence that produces the defect. Do not flag an effect as wrong without naming the failure.
6. Do not recommend `useMemo`, `useCallback`, or `React.memo` here; see `rendering-performance` for evidence rules.
