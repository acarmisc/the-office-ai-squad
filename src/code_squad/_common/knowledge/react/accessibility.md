---
title: Accessibility in React
source: WCAG 2.2 (W3C Recommendation, October 2023); WAI-ARIA Authoring Practices Guide; react.dev (Accessibility guidance); eslint-plugin-jsx-a11y
version: WCAG 2.2 level AA
reviewed: 2026-10
---

## Scope

Semantic markup, labels, keyboard operation, focus management, ARIA use, colour and text alternatives, in React components and JSX. The target is WCAG 2.2 AA unless the project states another level. Automated lint catches only part of the problem; mark findings that need manual testing as such.

## Rules

### REACT-A11Y-001 — Use native elements before ARIA

- **Look for:** `<div onClick>` or `<span onClick>` acting as buttons or links; `role="button"` added where a `<button>` would work.
- **Why it matters:** native elements provide focus, keyboard activation, and semantics for free.
- **Evidence:** the element, its handler, and the native alternative.
- **Bad:** `<div className="btn" onClick={save}>Save</div>`
- **Good:** `<button type="button" onClick={save}>Save</button>`
- **Default severity:** high (WCAG 4.1.2, 2.1.1).

### REACT-A11Y-002 — Every control has an accessible name

- **Look for:** `<input>`, `<select>`, `<textarea>` without `<label>`, `aria-label`, or `aria-labelledby`; icon-only buttons without an accessible name; placeholder used as the only label.
- **Why it matters:** screen readers announce no purpose; placeholders disappear on input.
- **Evidence:** the control and the absence of a name.
- **Default severity:** high (WCAG 1.3.1, 4.1.2).

### REACT-A11Y-003 — Keyboard operation and visible focus

- **Look for:** interactive custom widgets without keyboard handlers; `outline: none` without replacement focus style; `tabIndex` greater than zero; focus traps that cannot be exited.
- **Why it matters:** keyboard-only users cannot complete tasks.
- **Evidence:** the widget, the missing key handling, and the CSS rule removing focus.
- **Default severity:** high (WCAG 2.1.1, 2.4.7).

### REACT-A11Y-004 — Focus management for dynamic UI

- **Look for:** modals or dialogs that do not move focus in, trap focus, or return focus on close; route changes that leave focus on a removed element; toasts with no live region.
- **Why it matters:** focus is lost to the top of the page or to nothing.
- **Evidence:** the open or close handler and the focus target. Use native `<dialog>` where possible.
- **Default severity:** medium to high.

### REACT-A11Y-005 — ARIA is used correctly

- **Look for:** `aria-hidden="true"` on focusable elements; ARIA roles that conflict with the element (`role="button"` on `<a>` without reason); `aria-*` attributes not valid for the role; `aria-label` overriding visible text with different wording.
- **Why it matters:** incorrect ARIA is worse than none because it misinforms assistive technology.
- **Evidence:** the attribute and the element.
- **Default severity:** medium.

### REACT-A11Y-006 — Form errors are associated with fields

- **Look for:** validation messages rendered without `aria-describedby` or `aria-invalid`; error text that is only colour.
- **Why it matters:** users of assistive technology do not learn what failed.
- **Default severity:** medium (WCAG 3.3.1, 3.3.3).

### REACT-A11Y-007 — Text alternatives and images

- **Look for:** `<img>` without `alt` (decorative images need `alt=""`); SVG icons without a title or `aria-hidden` when decorative; images of text.
- **Default severity:** medium (WCAG 1.1.1).

### REACT-A11Y-008 — Colour and contrast

- **Look for:** new colour pairs below 4.5:1 for body text or 3:1 for large text and UI components; state conveyed only by colour.
- **Why it matters:** WCAG 1.4.3, 1.4.1, 1.4.11.
- **Evidence:** the colour values from the design tokens and the calculated ratio.
- **Default severity:** medium.

### REACT-A11Y-009 — Motion and timing

- **Look for:** animations without a `prefers-reduced-motion` alternative; auto-advancing content without a pause control; session timeouts without warning or extension.
- **Default severity:** low to medium (WCAG 2.2.1, 2.3.3).

### REACT-A11Y-010 — Headings and landmarks

- **Look for:** pages with no `<h1>`; heading levels skipped for styling; main content not in `<main>`; navigation without `<nav>`.
- **Default severity:** low.

## How to apply in review

1. Check the diff for native-element misuse first. These are the most common and cheapest to fix.
2. For each interactive element, confirm a name, a role, a keyboard path, and a visible focus indicator.
3. Mark findings that need a screen reader or keyboard test as `confidence: medium` and state the test.
4. Cite WCAG success criteria by number where applicable.
5. Respect the project's design system components if they already meet the criteria.
