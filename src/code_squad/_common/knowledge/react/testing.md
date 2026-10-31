---
title: Testing React applications
source: Testing Library documentation (guiding principles, queries); Mock Service Worker (MSW) documentation; Playwright documentation; Vitest and Jest documentation
version: Testing Library current major; Vitest 3.x or Jest 29+ (verify in package.json)
reviewed: 2026-10
unverified-edition: true
---

## Scope

Unit and component tests with Testing Library, network mocking with MSW, end-to-end tests with Playwright, and test quality. Applies to changes in test files and to changes that remove or weaken tests.

## Rules

### REACT-TEST-001 — Query by accessible role and label

- **Look for:** `getByTestId` as the first choice where roles or labels exist; `querySelector` in tests; queries by CSS class.
- **Why it matters:** role and label queries test what users and assistive technology see. Test ids test implementation.
- **Evidence:** the query and the available role or label.
- **Bad:** `screen.getByTestId('submit-btn')`
- **Good:** `screen.getByRole('button', { name: /save/i })`
- **Default severity:** low to medium.

### REACT-TEST-002 — Test behaviour, not implementation

- **Look for:** assertions on internal state, hook return values, or component instances; `jest.spyOn` on internal functions of the component under test; snapshots of whole component trees.
- **Why it matters:** refactors break tests without a user-visible change, and real defects pass.
- **Evidence:** the assertion and the implementation detail it relies on.
- **Default severity:** medium.

### REACT-TEST-003 — Async assertions wait for the outcome

- **Look for:** `setTimeout` or fixed sleeps in tests; `await` missing on `findBy` or `waitFor`; assertions run before the async state change.
- **Why it matters:** flaky tests that pass or fail based on timing.
- **Good:** `expect(await screen.findByText('Saved')).toBeInTheDocument();`
- **Default severity:** medium (flaky tests block merges).

### REACT-TEST-004 — Mock at the network boundary

- **Look for:** mocked `fetch` or axios modules replaced per test with ad hoc returns; mocks that do not match the real response shape; no error-path tests for network failure.
- **Why it matters:** the component sees real request and response behaviour. MSW handlers can be shared across tests and dev.
- **Evidence:** the mock and the production call it replaces.
- **Default severity:** low to medium.

### REACT-TEST-005 — Critical flows have end-to-end coverage

- **Look for:** login, checkout, data-loss-risk flows with unit tests only; e2e tests that depend on fixed sleeps or shared mutable test data.
- **Why it matters:** integration failures between client, server, and routing are not caught by component tests.
- **Evidence:** the flow and the absence of an e2e test that exercises it.
- **Default severity:** low to medium; medium for auth or payment.

### REACT-TEST-006 — Assertions exist and are meaningful

- **Look for:** tests without `expect`; tests that only render; snapshot tests updated without review (`-u` in CI or large snapshot diffs); `.skip` or `.only` committed; empty `catch` in tests.
- **Why it matters:** the suite reports green while checking nothing.
- **Evidence:** the test body and the skip or only marker.
- **Default severity:** medium.

### REACT-TEST-007 — Test isolation

- **Look for:** shared module state between tests; tests that depend on order; timers or dates not controlled (`vi.useFakeTimers`, fixed clock); random data without a seed.
- **Default severity:** low to medium.

### REACT-TEST-008 — Accessibility checks where the project has them

- **Look for:** new interactive components without an accessibility assertion or lint coverage where the project runs `jest-axe` or `vitest-axe`.
- **Default severity:** low.

## How to apply in review

1. Check whether the change weakened or removed tests before reviewing new ones.
2. Verify each new assertion can fail: consider the mutation that would break the behaviour.
3. Check the query strategy against the project's existing tests. Follow existing conventions.
4. Mark findings about flakiness as medium confidence unless the diff shows timing dependencies.
5. Cite the test file and line.
