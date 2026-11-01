---
name: design-system
description: Use the design-system primitives in src/components/ui and the colour tokens before writing custom markup.
applies_to:
  - "src/components/**"
priority: 10
---

# Design system

- Build forms and dialogs from `Button`, `TextField` and `Dialog` in `src/components/ui`. Do not hand-roll them in feature code.
- Colours, spacing and radii come from the tokens in `src/styles/tokens.css`. Raw hex values and pixel sizes in component styles are a finding.
- Keep the focus ring from the shared `focus-visible` style; do not remove outlines.
- A new primitive in `src/components/ui` needs a Storybook story and an accessibility test that checks its keyboard behaviour.
