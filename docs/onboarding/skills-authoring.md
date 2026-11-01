# Skills authoring

A skill is project guidance that the reviewers and `pam` read at run time. Skills carry conventions that a
generic rule cannot know: the design-system primitives to use, the transaction boundaries of a service, the
banned APIs, the naming of components. They are read from the repository, so the team that owns the code owns
the guidance.

Skills are guidance, never authority. A skill cannot add a tool, change the verdict rules, switch on writes or
change the output format. The loader ignores such attempts and records a warning.

## Where skills live

The default candidate directories, in precedence order, are:

1. `.agents/skills/`
2. `.claude/skills/`
3. `.squad/skills/`

Each skill is a directory with a `SKILL.md`:

```text
.agents/skills/
  design-system/
    SKILL.md
  transaction-rules/
    SKILL.md
```

The examples in the repository are `examples/repo/react-app/.agents/skills/design-system/SKILL.md` and
`examples/repo/java-service/.agents/skills/transaction-rules/SKILL.md`.

## Format

A `SKILL.md` starts with YAML frontmatter between `---` lines, followed by a markdown body.

| Key | Required | Meaning |
| --- | --- | --- |
| `name` | yes | Lower-case identifier: letters, digits, dots, dashes and underscores; starts with a letter or digit; at most 64 characters. |
| `description` | yes | One or two sentences. It is shown in the skill index, so write it for the reviewer deciding whether to load the skill. Up to 1024 characters. |
| `applies_to` | no | Glob patterns over the changed files. Without it the skill always applies. With it, the skill applies only when a changed file matches. |
| `agents` | no | Agent ids that may read the skill (for example `[angela]`). Without it, every reviewer and pam may read it. |
| `priority` | no | Integer. Higher priority is listed first when two skills of the same source compete. |
| `always` | no | `true` puts the body in the prompt instead of making the model call `load_skill`. Use it for a few short rules only. |

Unknown keys are ignored with a warning. Keys that try to set authority (`tools`, `allowed_tools`, `dry_run`,
`post`, `policy`, `output_schema`, `system`, `permissions`) are ignored with a warning too.

The body is ordinary markdown. Write it as rules the reviewer can check in the diff: what to use, what to avoid,
and what counts as a finding. A line that tries to override the platform rules (for example "ignore your
instructions" or "do not report") is replaced with a marker and a warning.

## Precedence

Skills are collected from three sources and merged by name:

| Source | Where it comes from | Rank |
| --- | --- | --- |
| Payload | The `skills` array of the invocation request, set by the caller | Highest |
| Repository | The candidate directories, read at the base branch by default | Middle |
| Built-in | The loader supports this source, but no built-in skills are loaded in this version. The baseline guidance is in the [knowledge packs](knowledge-packs.md). | Lowest |

When two skills share a name, the higher source replaces the lower one, and the result lists the override in
`skills_applied`. Repository skills are read at the base commit of the change request by default. A change to a
skill inside a change request applies after it is merged, and the summary flags that change.

`skills_ref: head` reads the skills from the change request head. It is an organisation decision, because it lets
a change request rewrite its own review rules. It logs a warning every time it is used.

## Limits

| Limit | Default | Platform ceiling |
| --- | --- | --- |
| Skills per run | 20 | `limits.max_skills` (50) |
| Bytes per skill body | 20480 | `limits.max_skill_bytes` (65536) |
| Total bytes per run | 81920 | `limits.max_total_skill_bytes` (262144) |

A body over the per-skill limit is truncated with a visible marker and a warning. Nothing is cut silently.

## Example: a React convention

```markdown
---
name: design-system
description: Use the design-system primitives in src/components/ui and the colour tokens before writing custom markup.
applies_to:
  - "src/components/**"
priority: 10
---

# Design system

- Build forms and dialogs from `Button`, `TextField` and `Dialog` in `src/components/ui`.
- Colours, spacing and radii come from `src/styles/tokens.css`. Raw hex values in component styles are a finding.
- Keep the shared focus ring. Do not remove outlines.
```

`applies_to` limits the skill to component files, so it is not loaded for a backend change.

## Example: a Java convention for one agent

```markdown
---
name: transaction-rules
description: Transaction boundaries and side effects in the service layer of the Java service.
applies_to:
  - "src/main/java/**/service/**"
agents:
  - angela
priority: 10
---

# Transaction rules

- Transactions begin in service methods. Read-only queries use `@Transactional(readOnly = true)`.
- Do not call remote HTTP services inside a transaction unless the call has an explicit timeout.
- Publish domain events after commit with `@TransactionalEventListener`.
```

`agents: [angela]` makes the skill visible to `angela` only.

## How a skill is used

1. The loader finds the directories, parses the frontmatter and drops invalid skills with a warning.
2. It selects the skills that match the changed files and the agent.
3. The reviewer receives the names and descriptions in its prompt. It calls `load_skill(name)` to read a body,
   or receives the body directly when `always: true`.
4. `get_project_skills` lists what applies and any warnings.
5. `stats.skills_applied` names the skills that were loaded.

Skill bodies are wrapped as untrusted content. The reviewer treats them as conventions, never as orders.

## Testing a skill

1. Validate the frontmatter by running the loader on the change: a dry-run invocation shows the skill in
   `stats.skills_applied` when it matches, and any problem appears in `warnings`.
2. Check the selection. A skill with `applies_to` must match a changed file in a real change request. Test
   the glob with a file path from that change.
3. Check the precedence if the name exists elsewhere. The result lists the override.
4. Run the skill tests in the repository: `just test tests/skills`. They cover precedence, limits, base-branch
   reading, hostile content and glob selection.

## Writing good skills

- One concern per skill. Several small skills are easier to keep correct than one long document.
- Say what counts as a finding and what does not. "Use `Button`" alone produces noise on code that predates the rule.
- Point at the code that defines the convention (a file path). The reviewer can then read it and confirm.
- Keep the body under a few kilobytes. Long references belong in a knowledge pack for the team, or in the repository docs.
- Review skills like code. A skill change is itself reviewed as part of the change request, and the summary flags it.
