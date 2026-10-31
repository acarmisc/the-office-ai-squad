# STATUS

Resume cold from here. The full brief is in `docs/BRIEF.md`; ADRs in `docs/decisions/`.

Current milestone: **M2 — VCS providers + findings pipeline** (M3 in parallel)

| # | Milestone | State |
|---|---|---|
| M0 | Repo bootstrap | done |
| M1 | Platform core | done |
| M2 | VCS providers + findings pipeline | todo |
| M3 | Configuration system | todo |
| M4 | Skills system | done |
| M5 | jim + angela | todo |
| M6 | dwight | todo |
| M7 | darryl | todo |
| M8 | Sandbox + pam | todo |
| M9 | Orchestrator (michael) | todo |
| M10 | Packaging & K8s | todo |
| M11 | Observability, docs, examples, eval | todo |

## Open risks

- Strands hook/limit APIs are recent (1.63); pinned in `uv.lock`.
- Docker daemon / kind availability in the build environment is unverified.

## Way of working

The solution architect designs each milestone and reviews; implementation is delegated
to sub-agents and reviewed before each commit.
