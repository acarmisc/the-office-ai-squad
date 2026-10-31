---
title: Dependency hygiene for React projects
source: npm documentation (package-lock.json, npm ci, peerDependencies); react.dev (Upgrading to React 19); OpenJS Foundation guidance on dependency maintenance
version: npm 10+; React 19.2
reviewed: 2026-10
---

## Scope

Adding, upgrading, and removing npm packages in React projects. Covers lockfile discipline, peer dependency resolution, duplicate React copies, dependency category, and bundle-weight judgement. Vulnerability triage for dependency changes belongs to `dwight` (`dependency-triage.md`); this file covers maintainability and correctness.

## Rules

### REACT-DEP-001 — Lockfile is committed and matches the manifest

- **Look for:** `package.json` changed without the lockfile; lockfile missing for an application; CI installs with `npm install` instead of `npm ci`.
- **Why it matters:** builds are not reproducible and the tested dependency tree differs from the released one.
- **Evidence:** the manifest change and the absent lockfile change in the same diff.
- **Default severity:** medium.

### REACT-DEP-002 — Peer dependency conflicts are resolved, not forced

- **Look for:** `--legacy-peer-deps`, `--force`, or `overrides` added to hide `ERESOLVE` errors; peer ranges that exclude the installed React version.
- **Why it matters:** the code may run against an untested React version. Hooks break when two React copies load.
- **Evidence:** the flag or override and the peer range it bypasses.
- **Default severity:** medium; high when React itself is overridden.

### REACT-DEP-003 — One React copy in the bundle

- **Look for:** multiple versions of `react` or `react-dom` in the lockfile for the same application (nested under another package); libraries that bundle their own React.
- **Why it matters:** hooks from one copy used in another throw "Invalid hook call" or silently misbehave.
- **Evidence:** lockfile entries for `react` and the dependent packages. Verify with `npm ls react`.
- **Default severity:** high.

### REACT-DEP-004 — Runtime dependencies are in the right category

- **Look for:** packages used at runtime listed under `devDependencies`; build tools (bundlers, type generators) listed under `dependencies` in applications.
- **Why it matters:** production installs miss required packages, or ship unnecessary ones.
- **Default severity:** low to medium.

### REACT-DEP-005 — New dependency is justified

- **Look for:** a new package that duplicates functionality already in the project; a utility library for one function; a large package for a small feature; a package with no maintenance activity.
- **Why it matters:** bundle size, supply chain surface, and maintenance cost.
- **Evidence:** the import, the existing alternative in the repo or platform, and the package size or maintenance signal.
- **Default severity:** low.

### REACT-DEP-006 — Major upgrades are isolated

- **Look for:** a React, router, or build tool major version bump mixed with unrelated feature changes; codemods run without the upgrade notes applied.
- **Why it matters:** failures cannot be attributed and reverting is harder.
- **Default severity:** medium.

### REACT-DEP-007 — Deprecated or unmaintained tooling

- **Look for:** `react-scripts` (Create React App is deprecated by the React team; see `migrations`); `enzyme` with React 18 or later; `react-test-renderer` in new tests; packages marked deprecated in the registry.
- **Why it matters:** no fixes for security or React compatibility.
- **Evidence:** the package name and its registry deprecation notice where visible.
- **Default severity:** low to medium.

### REACT-DEP-008 — Version ranges are deliberate

- **Look for:** `*`, `latest`, or very broad ranges for core packages (`react`, `react-dom`, the build tool); git URL dependencies without a commit pin.
- **Why it matters:** unexpected major versions enter without review.
- **Default severity:** medium for core packages; low otherwise.

## How to apply in review

1. Compare the manifest and lockfile changes in the same diff.
2. Run or request `npm ls react` output when a React-related dependency changes.
3. For each new package, state the alternative and why it is not used.
4. Route vulnerability and advisory questions to `dwight` and do not assert vulnerability status here.
5. Cite the manifest path and the exact package entry.
