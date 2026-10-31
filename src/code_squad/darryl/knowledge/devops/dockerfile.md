---
title: Dockerfile and container image review
source: Docker documentation (Dockerfile reference, multi-stage builds, BuildKit secret mounts, HEALTHCHECK, .dockerignore); CIS Docker Benchmark (checklist orientation only)
version: Docker Engine 27.x / BuildKit (current Dockerfile syntax 1.x)
reviewed: 2026-10
unverified-edition: true
---

## Scope

Review of `Dockerfile`, `Containerfile`, `.dockerignore`, and build scripts that produce images. Covers build reproducibility, image size and attack surface, runtime user, healthchecks, and secret handling during build. Kubernetes runtime settings are in `kubernetes-manifests.md`; security depth on privileges and images is in `security/docker-k8s-hardening`.

## Rules

### OPS-DOCK-001 — Multi-stage builds

- **Look for:** build toolchains (compilers, package managers with dev dependencies, source trees) present in the final image; `COPY . .` after dependency install in a single stage.
- **Why it matters:** larger images, larger attack surface, and more CVEs to triage.
- **Good:** a builder stage for compilation and tests, and a runtime stage that copies only the artefact.
- **Default severity:** medium.

### OPS-DOCK-002 — Base image pinning

- **Look for:** `FROM node:latest`, `FROM python` without version, floating tags for production images, and no digest pin where reproducibility is required.
- **Good:** a specific version tag at minimum; `@sha256:` digest for production, updated by an automated process.
- **Default severity:** medium; high for `latest` in production images.

### OPS-DOCK-003 — Non-root runtime user

- **Look for:** no `USER` instruction in the final stage; `USER root`; a user created without a fixed numeric id.
- **Good:** `RUN addgroup -S app && adduser -S app -u 10001` (or equivalent) then `USER 10001:10001`.
- **Default severity:** high (also `security/docker-k8s-hardening` SEC-DOCKER-001).

### OPS-DOCK-004 — Layer caching order

- **Look for:** `COPY . .` before dependency installation, so every source change re-runs installs; `RUN` steps that depend on changing files placed early.
- **Good:** copy manifests and lockfiles first, install, then copy the source.
- **Default severity:** low (build speed).

### OPS-DOCK-005 — Package installation hygiene

- **Look for:** `apt-get install` without `--no-install-recommends`; `apt-get update` in a separate `RUN` from `install` (stale cache); cache directories left in the image; `pip install` without `--no-cache-dir`; `apk add` without `--no-cache`.
- **Default severity:** low to medium.

### OPS-DOCK-006 — Healthcheck

- **Look for:** long-running service images without `HEALTHCHECK` and without a probe in the orchestrator manifest (note that Kubernetes probes replace image healthchecks; accept either, but at least one must exist).
- **Good:** a lightweight command that checks the service, with `--interval`, `--timeout`, `--retries`.
- **Default severity:** low.

### OPS-DOCK-007 — Entrypoint and signal handling

- **Look for:** `CMD npm start` in shell form (the shell becomes PID 1 and does not forward signals); `ENTRYPOINT` shell form with variable expansion where exec form is needed; no init process for services that spawn children.
- **Good:** exec form `CMD ["node", "server.js"]`; use an init (`tini` or `--init`) where child processes are spawned.
- **Default severity:** medium (slow shutdown, lost signals).

### OPS-DOCK-008 — Secrets in build

- **Look for:** `ARG` or `ENV` with secret values (persisted in image history); `COPY .env`; `RUN` that writes credentials to a file in a layer that is later deleted (still visible in earlier layers); tokens in `git clone` URLs.
- **Good:** BuildKit secret mounts (`RUN --mount=type=secret,id=npmrc ...`), which do not persist in layers.
- **Default severity:** high. Report location only.
- **Cross-reference:** `security/secrets-logging` SEC-SECRETS-004.

### OPS-DOCK-009 — ADD and remote content

- **Look for:** `ADD https://...` (no checksum, unclear caching); `curl | sh` installers; `ADD` of archives where `COPY` is enough (ADD extracts archives implicitly).
- **Good:** `COPY` for local files; download with a pinned version and a checksum verification step.
- **Default severity:** medium to high.

### OPS-DOCK-010 — .dockerignore

- **Look for:** no `.dockerignore`, or one that omits `.git`, `.env*`, `*.pem`, `node_modules` (when installed in the image), local build output, and IDE folders.
- **Why it matters:** the build context sends secrets and VCS history to the daemon and can copy them into the image.
- **Default severity:** medium; high when secret files are in the context.

### OPS-DOCK-011 — Writable paths and file ownership

- **Look for:** application directories owned by root that the non-root user must write to; `chmod -R 777`; `COPY` without `--chown` followed by a write at runtime.
- **Default severity:** medium.

### OPS-DOCK-012 — Ports, volumes, and metadata

- **Look for:** `EXPOSE` for unused ports; `VOLUME` declared in the Dockerfile for paths that should be provided at runtime; missing `LABEL` for source revision and version (traceability).
- **Good:** `LABEL org.opencontainers.image.revision` and `.version` set from build arguments.
- **Default severity:** low.

### OPS-DOCK-013 — Build reproducibility and provenance

- **Look for:** build arguments that change output without being recorded; builds that depend on the current date or network state without pinning; no build provenance or SBOM step in CI for release images.
- **Default severity:** low to medium.

### OPS-DOCK-014 — Compose and local orchestration files

- **Look for:** `privileged: true`, `network_mode: host`, host paths for the Docker socket, `latest` tags, secrets in `environment:` values in committed files.
- **Default severity:** medium to high.

## How to apply in review

1. Read the final stage first: user, entrypoint, exposed ports, and copied files.
2. Check the base image reference for pinning.
3. Check every `RUN` that touches secrets or the network.
4. Check `.dockerignore` against what `COPY` brings into the image.
5. Cite the Dockerfile line and the instruction. Suggest the smallest change that fixes the issue.
