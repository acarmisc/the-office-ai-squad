---
name: react-query-conventions
description: "Server state with TanStack Query: stable query keys, one hook per resource, explicit invalidation."
applies_to:
  - "src/**/*.ts"
  - "src/**/*.tsx"
priority: 10
---

# React Query conventions

- Keep one custom hook per resource (`useOrders`, `useOrder(id)`) next to the feature's API code. Components do not call `fetch` or the query client directly.
- Query keys are arrays that start with the resource name, for example `['orders', { status }]`. Build keys in one factory per resource so invalidation stays exact.
- After a mutation, invalidate the narrowest key that changed. Do not call `queryClient.clear()` from feature code.
- Do not copy server data into `useState`. Derive view state from the query result.
- Use `enabled` for dependent queries instead of conditional hook calls.
- Handle errors in the hook or at a route boundary. Do not turn a failed request into an empty list.
