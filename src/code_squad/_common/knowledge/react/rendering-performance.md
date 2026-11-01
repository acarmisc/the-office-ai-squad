---
title: Rendering performance
source: react.dev (Keeping Components Pure, Lists and Keys, Lazy Loading, useTransition, useDeferredValue); web.dev Core Web Vitals
version: React 19.2
reviewed: 2026-10
---

## Scope

Keys in lists, memoisation, expensive render work, virtualisation, code splitting, bundle size, and transitions. Performance claims need evidence: a profiler trace, a bundle report, a Web Vitals measurement, or a clearly described input size. Do not flag "possible" performance issues without a stated trigger.

## Rules

### REACT-PERF-001 — Keys are stable and unique

- **Look for:** `key={index}` on lists that can be reordered, filtered, or inserted into; keys generated with `Math.random()` or `Date.now()` during render; missing keys.
- **Why it matters:** React reuses component state by key. Wrong keys move state to the wrong row, which is a correctness bug before it is a performance bug.
- **Evidence:** the list, its mutation paths, and the key expression.
- **Bad:** `items.map((it, i) => <Row key={i} item={it} />)` where rows have local input state.
- **Good:** `items.map(it => <Row key={it.id} item={it} />)`.
- **Default severity:** medium; high when rows hold input state or side effects.

### REACT-PERF-002 — Memoisation needs evidence

- **Look for:** `useMemo`, `useCallback`, or `React.memo` added without a measured cost; memoised values that are cheap to compute; memoisation that never takes effect because props are recreated each render.
- **Why it matters:** memoisation adds comparison work and memory, and often does nothing when the inputs change every render.
- **Evidence:** the profiler result that justifies it, or the compiler setting in the project (React Compiler handles many cases automatically when enabled).
- **Rule of thumb:** memoise when a value is passed to a memoised child, is a dependency of an effect, or profiling shows the computation is expensive.
- **Default severity:** low. Raise only if the memo is actively wrong (stale values) or measurably harmful.

### REACT-PERF-003 — Long lists are virtualised

- **Look for:** rendering hundreds or thousands of rows without windowing; large tables with heavy cells.
- **Why it matters:** DOM size and render time grow linearly and degrade interaction latency.
- **Evidence:** the expected maximum item count from the data source or pagination limit, and the rendered row count.
- **Note:** pagination with a bounded page size can be preferable to virtualisation. Check before recommending a library.
- **Default severity:** medium.

### REACT-PERF-004 — Heavy code is split and lazy-loaded

- **Look for:** large libraries (charts, editors, PDF viewers, maps) imported at the top of routes that users may not open; no `lazy()` on route-level components.
- **Why it matters:** larger initial JavaScript slows first load and Largest Contentful Paint.
- **Evidence:** the import, the route it belongs to, and the bundle report if available.
- **Good:** `const Chart = lazy(() => import('./Chart'));` wrapped in `Suspense`.
- **Default severity:** medium.

### REACT-PERF-005 — Bundle impact of imports

- **Look for:** importing whole libraries (`import _ from 'lodash'`, `import * as icons from ...`); barrel files that pull in unused modules; large date or locale libraries for simple formatting.
- **Why it matters:** tree shaking is unreliable for some packages and barrels, so unused code ships.
- **Evidence:** the import statement and the package size reported by the bundler or `bundlephobia`-style analysis.
- **Default severity:** low to medium.

### REACT-PERF-006 — Expensive updates are interruptible

- **Look for:** heavy re-renders triggered by typing or filtering with no `useDeferredValue` or `startTransition`; synchronous expensive computation in render.
- **Why it matters:** input becomes laggy because urgent updates wait behind slow renders.
- **Evidence:** the input handler, the render it triggers, and the profiler trace showing blocking time.
- **Default severity:** low to medium; raise only with measured input latency.

### REACT-PERF-007 — Images and media have dimensions

- **Look for:** `<img>` without `width` and `height` or an aspect-ratio container; eager loading for offscreen images; large unoptimised images.
- **Why it matters:** layout shift (CLS) and wasted bandwidth.
- **Evidence:** the image element and its container.
- **Default severity:** low.

### REACT-PERF-008 — Render functions are pure

- **Look for:** mutations of props, state, or module-level variables during render; side effects such as network calls or `localStorage` writes in the component body.
- **Why it matters:** pure render is required for concurrent features and Strict Mode. Impure render produces inconsistent output.
- **Evidence:** the mutating statement in the render body.
- **Default severity:** medium.

## How to apply in review

1. Ask what input size or trigger the change assumes. If the answer is unknown, lower confidence.
2. Prefer correctness findings (keys with state, stale memo) over speculative performance findings.
3. Cite a profiler output, bundle report, or code path with an input-size estimate.
4. Do not request `React.memo` on leaf components without a measured reason.
5. Check whether the project uses React Compiler before recommending manual memoisation.
