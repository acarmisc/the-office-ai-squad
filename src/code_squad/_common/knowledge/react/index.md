---
title: React knowledge pack index
source: Project-authored index of the react/ knowledge pack
version: React 19.2 (see individual topics for other versions)
reviewed: 2026-10
---

## Scope

Index of the shared React pack used by `jim` (React reviewer) and `pam` (frontend engineer). Topic id is the file path without `.md`, for example `react/hooks-and-effects`. Load a topic with `read_knowledge(topic)` only when the diff touches its area.

## Rules

Topics:

- `react/hooks-and-effects`: hook rules, effect dependencies, fetch races, derived state in effects, Strict Mode idempotence.
- `react/state-and-data-fetching`: state placement, context and store use, server-state libraries, query keys, mutations and optimistic updates.
- `react/rendering-performance`: keys, memoisation evidence, virtualisation, code splitting, bundle impact, transitions.
- `react/server-components-nextjs`: Server Components, client boundaries, Server Actions, framework caching. Applies only to RSC or Next.js App Router projects.
- `react/typescript`: `any` leakage, discriminated unions, casts and non-null assertions, runtime validation of external data, strict settings.
- `react/accessibility`: native elements, labels, keyboard operation, focus management, ARIA use, contrast, WCAG 2.2 AA.
- `react/forms-and-validation`: controlled inputs, client versus server validation, submission guards, form Actions.
- `react/error-handling-suspense`: error boundaries, async errors boundaries miss, swallowed errors, Suspense waterfalls, error disclosure.
- `react/testing`: Testing Library queries, behaviour over implementation, async waits, MSW, Playwright, test quality.
- `react/security-adjacent`: `dangerouslySetInnerHTML`, URL sinks, `postMessage`, token storage, client-bundle secrets, dynamic code.
- `react/dependency-hygiene`: lockfile discipline, peer conflicts, duplicate React copies, dependency categories, deprecated tooling.
- `react/component-design`: responsibility, composition, components defined in components, keys and identity, custom hooks.
- `react/project-structure`: layout conformity, module boundaries, cycles, barrels, shared code.
- `react/migrations`: class to function, CRA to Vite, React 18 to 19 checklists.

Rule id prefixes: `REACT-HOOKS`, `REACT-STATE`, `REACT-PERF`, `REACT-RSC`, `REACT-TS`, `REACT-A11Y`, `REACT-FORM`, `REACT-ERR`, `REACT-TEST`, `REACT-SEC`, `REACT-DEP`, `REACT-COMP`, `REACT-STRUCT`, `REACT-MIG`.

## How to apply in review

1. Detect the React, framework, and TypeScript versions from `package.json`, the lockfile, and `tsconfig.json` before loading topics.
2. Load only the topics the changed files need.
3. Project conventions and skills override these defaults, but never lower a correctness or security finding below its floor.
4. Cite the rule id, the file, and the line in every finding.
