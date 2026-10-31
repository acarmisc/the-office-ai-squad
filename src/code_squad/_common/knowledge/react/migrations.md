---
title: Migrations: class to function, CRA to Vite, React 18 to 19
source: react.dev (Upgrading to React 19; Hooks FAQ; Create React App deprecation notice); Vite documentation (Env Variables and Modes); React 19 upgrade guide
version: React 19.2; Vite 6+ (verify current major in package.json)
reviewed: 2026-10
---

## Scope

Review checklists for three migrations: class components to function components, Create React App (CRA) to Vite, and React 18 to React 19. Use these checklists to verify that a migration is complete and behaviour-preserving. Verify the target version in the lockfile before relying on a removal list.

## Rules

### REACT-MIG-001 — Class to function: lifecycle mapping preserved

- **Look for:** `componentDidMount`, `componentDidUpdate`, `componentWillUnmount` converted to effects without matching cleanup or dependency handling; `getDerivedStateFromProps` replaced with state copied from props (see REACT-STATE-002); `this.setState` calls replaced with stale reads.
- **Why it matters:** behaviour changes between mount and update, and subscriptions leak.
- **Mapping:** `componentDidMount` plus `componentWillUnmount` maps to one `useEffect` with cleanup. `componentDidUpdate` maps to an effect with the relevant dependencies, not to an effect with no dependencies unless intended.
- **Evidence:** the original lifecycle method and the converted effect.
- **Default severity:** high when subscriptions or fetches change behaviour; medium otherwise.

### REACT-MIG-002 — Error boundaries remain class components

- **Look for:** attempts to convert error boundaries to function components with no class fallback, or a hook-based error boundary library used without checking its implementation.
- **Why it matters:** React has no hook equivalent for `componentDidCatch` and `getDerivedStateFromError`. Keep the class boundary or use a maintained library.
- **Default severity:** high if the boundary is removed or non-functional.

### REACT-MIG-003 — Class to function: instance fields and refs

- **Look for:** `this.field` values converted to `useState` when they do not affect rendering (should be `useRef`); `createRef` replaced with `useRef` but the initial value omitted (React 19 requires an argument to `useRef`).
- **Default severity:** medium.

### REACT-MIG-004 — CRA to Vite: environment variables

- **Look for:** `process.env.REACT_APP_*` still in source after migration; `import.meta.env` used without the `VITE_` prefix configured; `process.env.NODE_ENV` checks that behave differently under Vite.
- **Why it matters:** configuration is undefined at runtime. Under Vite, only variables with the `VITE_` prefix are exposed to client code by default.
- **Evidence:** the variable reference and the Vite config `envPrefix`.
- **Default severity:** high (silent misconfiguration).

### REACT-MIG-005 — CRA to Vite: entry point and assets

- **Look for:** `public/index.html` still referenced by the Vite entry; `%PUBLIC_URL%` placeholders not replaced; asset paths using absolute URLs that break under a base path; SVG imports relying on CRA's default loader without the Vite plugin.
- **Default severity:** medium.

### REACT-MIG-006 — CRA to Vite: test and tooling parity

- **Look for:** Jest configuration left in place while tests run under Vitest without parity; `setupTests` path changes missing; CSS module or SVG mocks not mirrored; ESLint configuration left in CRA format.
- **Default severity:** medium.

### REACT-MIG-007 — CRA to Vite: deployment and routing

- **Look for:** build output directory changed from `build/` to `dist/` without updating the CI artifact path, Dockerfile, or hosting rules; client-side routes missing a fallback to `index.html` on the host.
- **Default severity:** high (deployment break); cross-reference `OPS-*` rules.

### REACT-MIG-008 — React 18 to 19: removed APIs

- **Look for:** `ReactDOM.render`, `ReactDOM.hydrate`, and `unmountComponentAtNode` (replaced by `createRoot` and `hydrateRoot`); `ReactDOMTestUtils.act` (use `React.act`); `ReactDOM.findDOMNode`; `react-dom/test-utils` imports; legacy Context via `contextTypes`; string refs.
- **Why it matters:** removed APIs fail at build or runtime.
- **Default severity:** high.

### REACT-MIG-009 — React 18 to 19: prop types and defaults on function components

- **Look for:** `propTypes` and `defaultProps` on function components. React 19 removes support for these on function components. Replace with default parameter values and TypeScript types. `defaultProps` on class components still works.
- **Default severity:** medium (runtime warnings or ignored defaults).

### REACT-MIG-010 — React 18 to 19: refs and forwardRef

- **Look for:** `forwardRef` wrappers that could now accept `ref` as a prop; ref callbacks that return values where cleanup is expected (React 19 supports cleanup functions returned from ref callbacks, and the old pattern of returning a non-function value is an error).
- **Default severity:** low to medium.

### REACT-MIG-011 — React 18 to 19: Context and form APIs

- **Look for:** `<Context.Provider>` still used where the project moves to `<Context>` (both work; flag only if a lint rule or the team standard requires the change); `useFormState` replaced by `useActionState`; `react-dom` form status hooks misused (see REACT-FORM-006).
- **Default severity:** low.

### REACT-MIG-012 — React 18 to 19: errors and root options

- **Look for:** code relying on the old console error output for caught errors; missing `onCaughtError` and `onUncaughtError` options where error reporting is expected (see REACT-ERR-008).
- **Default severity:** low.

### REACT-MIG-013 — React 18 to 19: types and JSX runtime

- **Look for:** `@types/react` and `@types/react-dom` not upgraded to the matching major version; global `JSX` namespace references (removed from `@types/react` 19 in favour of React-scoped types); JSX transform not set to the automatic runtime.
- **Why it matters:** type errors or unexpected `React is not defined` errors in older code.
- **Default severity:** medium.

### REACT-MIG-014 — React 18 to 19: test behaviour

- **Look for:** tests that depend on synchronous updates without `act`; snapshot changes caused by new error output; `react-test-renderer` usage (deprecated in favour of other test tooling for React 19).
- **Default severity:** low to medium.

### REACT-MIG-015 — Migration is done in reviewable steps

- **Look for:** class conversion, bundler change, and React major upgrade in one change; no test run evidence; codemods applied and then not reviewed.
- **Why it matters:** behavioural regressions cannot be attributed.
- **Good:** one migration per change, each with a passing test suite and a manual smoke test.
- **Default severity:** medium.

## How to apply in review

1. Identify the migration type from the diff: class-to-function, CRA-to-Vite, or React major version.
2. Use the matching checklist. Confirm each removed API is gone, and each replacement is present.
3. Verify test evidence exists for each behaviour-changing conversion.
4. State the version assumptions explicitly (React 19.2 and current Vite major) and note when a project is on a different version.
5. Escalate deployment-path changes to `darryl` for CI and artifact review.
