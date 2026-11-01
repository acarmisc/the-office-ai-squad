## Summary

<!-- What changes, and why. One paragraph is enough. -->

## Linked issue and decision

- Issue: <!-- Closes #123, or "none" -->
- ADR: <!-- docs/decisions/NNNN-title.md when the change makes a non-trivial choice, or "not needed" -->

## Checklist

- [ ] `just check` is green locally (or the CI run is green, with the reason for any local gap below)
- [ ] Tests added or updated. A bug fix has a regression test that fails before the fix.
- [ ] A security-relevant change (tool policy, dry run, untrusted content, validation, secrets, configuration layers) tests the refusal,
      not only the success path
- [ ] Generated references are up to date (`just docs-gen`) when a schema, a tool or a configuration key changed
- [ ] Documentation updated for any user-visible change, and `just docs` passes
- [ ] `CHANGELOG.md` has an entry under `## Unreleased` for user-visible changes or configuration defaults
- [ ] No secrets, tokens, real hosts or customer data in code, tests, fixtures, logs or docs
- [ ] Conventional commit messages in the imperative mood

## Notes for reviewers

<!-- Risks, trade-offs, what to look at first, how you checked it (dry run, replay, smoke test). -->
