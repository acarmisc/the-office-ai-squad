---
title: Forms and validation
source: react.dev (Reacting to Input with State, Forms guidance); React 19 Actions documentation; WCAG 2.2 (3.3 Input Assistance)
version: React 19.2
reviewed: 2026-10
---

## Scope

Form state, controlled and uncontrolled inputs, client-side and server-side validation, submission state, and error presentation. Covers plain React forms, React 19 form Actions (`useActionState`, `useFormStatus`), and schema-based libraries.

## Rules

### REACT-FORM-001 — Controlled inputs are consistently controlled

- **Look for:** `value` without `onChange` (read-only by accident); `value` switching between `undefined` and a string; inputs that change between controlled and uncontrolled across renders.
- **Why it matters:** React warns, and the input may ignore typing or lose its value.
- **Evidence:** the input props and the state initialisation.
- **Default severity:** medium.

### REACT-FORM-002 — Client validation is not a security control

- **Look for:** authorisation, limits, or business rules enforced only in the browser; server handlers that trust fields because the form validated them.
- **Why it matters:** any client can post arbitrary data. Client checks improve UX only.
- **Evidence:** the validation code and the server endpoint that receives the same fields without equivalent checks.
- **Default severity:** high when the rule protects data or money; medium otherwise. Cross-reference `SEC-INJECT-*` and `SEC-ACCESS-*`.

### REACT-FORM-003 — Errors are announced and linked

- **Look for:** error messages not associated with the field (`aria-describedby`); `aria-invalid` missing; no summary for multi-field forms; errors shown only in colour.
- **Why it matters:** assistive technology users do not learn what to fix. WCAG 3.3.1 and 3.3.3.
- **Default severity:** medium. See `accessibility`.

### REACT-FORM-004 — Submission is guarded

- **Look for:** submit buttons not disabled while a request is pending; no guard against double submission; no feedback on success or failure; navigation after submit without waiting for the result.
- **Why it matters:** duplicate records and payments, and confusing outcomes.
- **Evidence:** the submit handler and the pending-state logic.
- **Default severity:** medium; high for payment or irreversible actions.

### REACT-FORM-005 — One validation schema

- **Look for:** the same rule written in the form component, the API handler, and the database layer with different limits.
- **Why it matters:** rules drift. A value accepted by the form is rejected by the API, or the reverse.
- **Good:** a shared schema module imported by both client and server, or generated from the API contract.
- **Default severity:** low to medium.

### REACT-FORM-006 — Form Actions use the framework's pending and error flow

- **Look for:** `useActionState` or `useFormStatus` misused (for example, `useFormStatus` called in the component that renders the `<form>` rather than a child); action errors thrown instead of returned where the UI expects state; missing `name` attributes that the action reads from `FormData`.
- **Why it matters:** the pending state is never shown, or the action receives empty data.
- **Evidence:** the hook call location and the form element.
- **Default severity:** medium.

### REACT-FORM-007 — Sensitive fields are handled deliberately

- **Look for:** passwords or tokens in `value` attributes or logged state; autocomplete attributes missing on credential fields; sensitive values stored in URL query strings.
- **Why it matters:** secrets leak to logs, history, and referrers.
- **Evidence:** the field, the state or URL, and the log or storage call.
- **Default severity:** high. Cross-reference `SEC-SECRETS-*`.

### REACT-FORM-008 — Input limits match server limits

- **Look for:** no `maxLength` or length validation on text fields that the backend limits; numeric inputs without range checks.
- **Default severity:** low.

## How to apply in review

1. Identify which validation runs where. Mark any rule that exists only on the client.
2. Check the submit path for double-submit protection and a clear result state.
3. Check each error message for an association with its field.
4. Cite the component file and the server handler when comparing rules.
5. Do not recommend a form library unless the existing code shows repeated, error-prone form logic.
