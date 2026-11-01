# 0012 — Agent naming: The Office ids, one mapping, functional role names

- Status: accepted
- Date: 2026-11-01

## Context

The squad has six built-in agents. Their ids appear in many places that are hard to change later: the `AGENT_NAME`
variable, package directories, Kubernetes object names, commit statuses, branch names, configuration keys and logs. People
must still recognise what each agent does from the documentation and from the prompts. The brief (sections 2 and 4) asks
for short ids taken from The Office (US), with functional role names in the documentation and no character humour.

## Decision

- **Ids.** `michael` (orchestrator), `jim` (React reviewer), `angela` (Java reviewer), `dwight` (security reviewer),
  `darryl` (DevOps specialist) and `pam` (senior frontend engineer). Each id is a lowercase single token. The ids are used
  for `AGENT_NAME`, the package directory `src/code_squad/<id>/`, the Kubernetes objects `code-squad-<id>`, the commit
  statuses `ai-review/<id>` and the branches `<id>/<task-key>-<slug>`.
- **One mapping.** `AGENT_IDS` and `ROLES` in `_common/registry.py` are the only code mapping. The chart's `agents` keys and
  the docs table follow them. `tests/test_registry.py` checks that the specs carry the mapped roles.
- **Functional role names in docs and prompts.** Documentation names an agent by its id and its role, for example
  "`dwight`, security reviewer". Each `prompt.md` title is the id's display name and the role, for example
  "Dwight — security reviewer". The prompt describes the role, and no prompt depends on the character.
- **No persona humour.** The name is only a name. Prompts, summaries, comments, statuses and logs stay professional, with
  no character quotes, jokes or in-character asides.
- **Extra agents keep their own names.** Agents declared in organisation configuration use the names chosen there and are
  not part of this mapping. They are registered at start-up (ADR 0010).

## Consequences

- Renaming an id is a breaking change: it changes the Kubernetes objects, the commit status contexts, the branch prefixes
  and the configuration keys. Such a change needs its own ADR and a migration note.
- A new built-in agent needs an entry in `AGENT_IDS` and `ROLES`, a package, a prompt in the matching directory, and a
  chart entry. The prompt test (`tests/test_prompts.py`) and the registry test fail until all four exist.
- Readers who know the characters still find the agent quickly, and readers who do not know them read the role.
