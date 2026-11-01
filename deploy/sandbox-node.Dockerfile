# Sandbox image for pam's KubernetesJobSandbox pods (one pod per invocation).
# Holds no credentials and no application code: git plus a Node LTS toolchain.
# pnpm and yarn come from corepack.
#
# Build: docker build -f deploy/sandbox-node.Dockerfile -t code-squad-sandbox-node:0.1.0 .

FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# corepack ships the pnpm and yarn shims. The pinned versions are fetched on first use
# through registry egress (allowed by the sandbox NetworkPolicy). The cache lives on the
# writable workspace volume because the root filesystem is read-only.
RUN corepack enable

# Non-root sandbox user (uid 10002). Its home is the workspace volume.
RUN groupadd --system --gid 10002 sandbox \
    && useradd --system --uid 10002 --gid 10002 \
        --no-create-home --home-dir /workspace --shell /usr/sbin/nologin sandbox \
    && mkdir -p /workspace \
    && chown 10002:10002 /workspace

ENV HOME=/workspace \
    COREPACK_HOME=/workspace/.cache/corepack \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    NPM_CONFIG_CACHE=/workspace/.cache/npm

WORKDIR /workspace

USER 10002:10002

CMD ["sleep", "infinity"]
