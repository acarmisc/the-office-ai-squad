# 0004 — Skills are read from the base branch by default

- Status: accepted
- Date: 2026-10-31

## Context

Runtime skills carry project conventions into the reviewers and `pam` (BRIEF §6). They
are discovered in the target repository at `.agents/skills`, `.claude/skills` or
`.squad/skills`. A change request (CR) can edit those same files. If the review rules
were read from the CR head, a CR could weaken the rules that review it, and the
reviewer would not notice.

## Decision

- Repository skills are read at the **base** ref of the change request (the target
  branch commit) by default (`skills_ref: base`).
- `skills_ref: head` is available. It reads the CR head SHA, and the loader records the
  warning "skills read from change request head (skills_ref=head); review rules may be
  modified by this change".
- Skill files changed by the CR are reported in `SkillSet.changed_in_change_request` so
  the summary can flag them, whichever ref is used.
- Precedence is payload > repo > builtin. A higher-precedence skill with the same name
  replaces the lower one and is recorded in `SkillSet.overrides`.
- A skill body is guidance only. Frontmatter keys that try to set authority (`tools`,
  `allowed_tools`, `dry_run`, `post`, `policy`, `output_schema`, `system`,
  `permissions`) are ignored with a warning. Body lines that try to override system
  rules are replaced by a marker with a warning. Every body is wrapped as untrusted
  content.
- Skill caches are keyed by the commit SHA, so a new base commit reads fresh skills.
  Caching requires an immutable SHA ref.

## Alternatives considered

- **Read from the CR head.** Lets a CR change its own review rules without a visible
  signal. Rejected as the default. It stays available as an explicit opt-in for teams
  that accept the risk.
- **Read from the default branch name.** A branch name is not immutable, so cached
  results could go stale. Rejected: the base commit SHA is used instead.

## Consequences

- A skill added or changed in the same CR as the code it governs does not apply to that
  review until it is merged. Teams that need this use `skills_ref: head` and accept the
  warning.
- Skill files in a CR are visible in the summary whichever ref is used.
- Removing a line that matches an override pattern can remove legitimate guidance. The
  pattern `do not report` is intentionally broad; a skill that needs that phrase must
  rephrase it.
