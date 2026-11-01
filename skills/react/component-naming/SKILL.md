---
name: component-naming
description: Naming and file layout for React components, hooks, props types and tests.
applies_to:
  - "src/**/*.tsx"
  - "src/**/*.jsx"
priority: 5
---

# Component naming

- One exported component per file. The file name matches the component name in PascalCase (`OrderList.tsx` exports `OrderList`).
- Hooks start with `use` and live in a file named after the hook (`useOrderFilters.ts`).
- Props types are named `<Component>Props` and sit above the component in the same file.
- Tests are colocated as `<Component>.test.tsx` and query the DOM by role and label.
- Boolean props read as predicates (`isOpen`, `hasError`). Avoid negated names (`notVisible`).
- Shared primitives belong under `src/components/ui`; feature components stay in their feature folder.
