<!-- generated — do not edit. Source: scripts/gen_docs.py. Regenerate with: just docs-gen -->

# Agent defaults

Generated from the `SPEC` of every built-in agent. These are the built-in defaults.
The organisation file, the project registry and the repository file can change the
model, token and iteration settings (`agents.<id>`), within the platform limits.

| Id | Role | Modes | Default model | Max tokens | Temperature | Max iterations | Tools | External writes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `michael` | orchestrator | review, troubleshoot, implementer, question | `haiku-5-5` | 8192 | 0 | 25 | 2 | none |
| `jim` | react-reviewer | review | `sonnet-5-5` | 8192 | 0 | 25 | 9 | `publish_review` |
| `angela` | java-reviewer | review | `sonnet-5-5` | 8192 | 0 | 25 | 9 | `publish_review` |
| `dwight` | sec-reviewer | review | `sonnet-5-5` | 8192 | 0 | 30 | 13 | `publish_review` |
| `darryl` | devops | review, troubleshoot | `sonnet-5-5` | 8192 | 0 | 30 | 21 | `publish_review` |
| `pam` | frontend-dev | advisor, implementer | `sonnet-5-5` | 16384 | 0 | 60 | 19 | `push_branch`, `open_change_request` |

## Descriptions

- `michael`: Routes requests to specialist agents and consolidates their results.
- `jim`: Reviews React and TypeScript changes.
- `angela`: Reviews Java and JVM changes, including Spring applications.
- `dwight`: Assesses the security posture of code, config and dependencies.
- `darryl`: Reviews CI/CD, containers, IaC and Kubernetes manifests, and troubleshoots production issues with read-only access.
- `pam`: Senior React engineer: plans frontend work and implements tasks.
