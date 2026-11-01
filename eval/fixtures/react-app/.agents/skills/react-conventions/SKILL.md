---
name: react-conventions
description: Team conventions for React components and data fetching
applies_to: ["src/**/*.tsx", "src/**/*.ts"]
---
Fetch data in query hooks or in the data layer, not inside presentational components.
Name custom hooks with a `use` prefix and keep them in `src/hooks/`.
Render user-supplied text as text, never as HTML.
