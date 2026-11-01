# Decisions

Architecture decision records (ADRs) capture the choices that shape the squad, the context in which each was made, and the
consequences. They are short, and each one names the modules that implement it. Read the ADR before you change the behaviour it
describes. For how to add one, see the [contributing guide](../contributing/index.md#adr-process).

| ADR | Title | Status | Date | Summary |
| --- | --- | --- | --- | --- |
| [0001](0001-stack.md) | Stack: Strands Agents and FastAPI, uv, Python 3.12 | accepted | 2026-10-31 | Agent loop on Strands with an OpenAI-compatible model behind LiteLLM; HTTP on FastAPI; provider code is confined to one module. |
| [0002](0002-runtime-semantics.md) | Runtime semantics: retries, dry run and payload strictness | accepted | 2026-10-31 | One retry; `incomplete` on the turn limit; `failed` on a model error; `post` must be a boolean; unclassified tools refused. |
| [0003](0003-configuration-layering.md) | Configuration layering, tighten-only rules and hot reload | accepted | 2026-10-31 | Five layers; whole-layer rejection; floor rules; provenance; effective config hash; hot reload with a safe fallback. |
| [0004](0004-skills-from-base-branch.md) | Skills are read from the base branch by default | accepted | 2026-10-31 | A change request cannot rewrite its own review rules; authority keys in skills are ignored. |
| [0005](0005-sandbox-backend.md) | Sandbox backend: one ephemeral pod per invocation | accepted | 2026-11-01 | Kubernetes pod per pam run with no secrets, a command allow-list, scoped git credentials and destruction in a `finally`. |
| [0006](0006-darryl-read-only.md) | darryl is read-only by construction | accepted | 2026-11-01 | No mutation tools; read-only RBAC without secrets; redacted, bounded output. |
| [0007](0007-no-approval-gate-for-pam.md) | No approval gate for pam (implementer mode) | accepted | 2026-11-01 | No plan approval; twelve compensating controls enforced in code, starting with isolation and protected paths. |
| [0008](0008-per-invocation-services.md) | Per-invocation services, fail-closed configuration and knowledge lookup order | accepted | 2026-11-01 | Services built per request; an invalid organisation file turns writes off; knowledge read from the agent pack, then shared, then extra directories. |
| [0009](0009-dwight-offline-mode.md) | dwight offline and restricted-egress behaviour and the verdict guard | accepted | 2026-11-01 | Missing advisory data is marked unverified; an approve is withheld on dependency changes; the rule is repeated at publication. |
| [0010](0010-orchestrator-single-publication-path.md) | Single publication path through the orchestrator | accepted | 2026-11-01 | Specialists return findings; michael publishes one summary and one status; any incomplete specialist makes the verdict incomplete. |
| [0011](0011-vcs-abstraction.md) | VCS abstraction: protocol, capability flags, GitHub App first, no merge | accepted | 2026-11-01 | One `VcsProvider` protocol with capability flags and warned fallbacks; GitHub App preferred over a token; a conformance suite every provider passes; no merge operation. |
| [0012](0012-agent-naming.md) | Agent naming: The Office ids, one mapping, functional role names | accepted | 2026-11-01 | Six lowercase ids from The Office; one mapping in `registry.py`; functional role names in docs and prompts; no persona humour. |

## How the ADRs relate

- ADR 0001 sets the stack. ADR 0002 defines what a run can end as, and ADR 0003 defines the configuration that decides the limits.
- ADR 0004 and ADR 0003 together decide where review rules come from and who can change them.
- ADR 0005, ADR 0006, ADR 0007 and ADR 0009 are the controls for the three agents with the most reach: pam, darryl and dwight.
- ADR 0008 and ADR 0010 describe how a single request is served and published.
- ADR 0011 defines the forge boundary that the publication and `pam` code rely on. ADR 0012 defines the ids used everywhere.

## Open points raised in the ADRs

These points are recorded as open in the decisions themselves. They are collected in the [handoff](../HANDOFF.md#open-decisions).

- Whether `review.ignore_globs` and `security.accepted_risks` should be organisation-only (ADR 0003, ADR 0009).
- Restricting accepted risks to the organisation layer (ADR 0009).
- A process-wide intelligence service keyed by the security configuration, so the NVD rate window and the caches are shared (ADR 0009).
- Whether the orchestrator should ever submit a formal approval (ADR 0010).
- Job-based sandbox pods, so orphaned pods are deleted (ADR 0005).
