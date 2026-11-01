# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately. Do not open a public issue, a pull request or a discussion for a security problem.

Use GitHub's private vulnerability reporting:
**[Report a vulnerability](https://github.com/acarmisc/the-office-ai-squad/security/advisories/new)**.

Include, when you can:

- the version or commit, and the deployment mode (Helm chart, Compose, or a single process);
- the configuration that matters, with every secret removed;
- the steps to reproduce, and what you expected and what happened;
- the impact as you understand it.

Never include real tokens, customer data or private repository contents. A redacted example that shows the problem is enough.

## What to expect

The maintainers acknowledge a report, assess it against the [threat model](docs/security/threat-model.md), and agree a fix and a
disclosure date with you. When a fix changes a security control, the change is recorded in an ADR and the changelog. Credit is given
in the advisory unless you ask otherwise.

## Supported versions

| Version | Security fixes |
| --- | --- |
| `main` | Yes |
| Latest release tag (`0.x`) | Yes, until the next release |
| Older tags | No; upgrade |

Pre-release tags (`vX.Y.Z-rc.N`) receive fixes only through the next release.

## Scope

In scope: the code in this repository, the Helm chart, the Dockerfiles and the example files, when they lead to a weakness the
documentation says is prevented (for example a write in dry run, a secret in a log, an unauthenticated route, a tool that changes a
cluster, or a repository file that loosens an organisation rule).

Out of scope:

- a deployment that does not follow the [hardening checklist](docs/security/hardening.md), unless the default settings are the cause;
- the behaviour of third-party services (GitLab, GitHub, the LLM gateway, the advisory sources) and of the models;
- findings from automated scanners without a demonstrated impact;
- denial of service through very large inputs when the documented limits are configured.

## Hardening guidance

Operators should read [Hardening](docs/security/hardening.md) and [Threat model](docs/security/threat-model.md) before go-live. The
known limitations that affect security are listed in [Handoff](docs/HANDOFF.md#known-limitations).
