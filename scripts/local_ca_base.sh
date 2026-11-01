#!/usr/bin/env bash
# Build a local Python base image that trusts a corporate or proxy CA.
#
# ONLY FOR TLS-INTERCEPTING PROXY ENVIRONMENTS (sandboxes where outbound HTTPS is re-signed
# by a proxy CA). Inside such an environment `uv sync` in deploy/Dockerfile fails with
# UnknownIssuer. This script is not part of the delivery path: CI and production builds use
# the default PYTHON_IMAGE=python:3.12-slim and never call it. The committed Dockerfile is
# not changed. Use the result with:
#
#   scripts/local_ca_base.sh /root/.ccr/ca-bundle.crt
#   PYTHON_IMAGE=cs-local/python:3.12-slim-ca docker compose -f deploy/compose.yaml build
#   IMAGE=code-squad:dev PYTHON_IMAGE=cs-local/python:3.12-slim-ca deploy/kind/kind-up.sh
#
# Usage: scripts/local_ca_base.sh CA_BUNDLE_PATH [IMAGE_TAG]
#   CA_BUNDLE_PATH  PEM file with the proxy CA(s). Required: there is no default.
#   IMAGE_TAG       defaults to cs-local/python:3.12-slim-ca
set -euo pipefail

BASE_FROM="python:3.12-slim"
DEFAULT_TAG="cs-local/python:3.12-slim-ca"

if [[ $# -lt 1 || -z "${1}" ]]; then
  echo "error: pass the path to the proxy CA bundle, for example /root/.ccr/ca-bundle.crt." >&2
  echo "This helper exists only for TLS-intercepting proxy environments; see its header." >&2
  exit 2
fi
CA_BUNDLE="$1"
TAG="${2:-${DEFAULT_TAG}}"

if [[ ! -r "${CA_BUNDLE}" ]]; then
  echo "error: CA bundle ${CA_BUNDLE} is missing or not readable" >&2
  exit 2
fi
if ! command -v docker >/dev/null; then
  echo "error: docker is required" >&2
  exit 2
fi

CONTEXT="$(mktemp -d)"
trap 'rm -rf "${CONTEXT}"' EXIT
cp "${CA_BUNDLE}" "${CONTEXT}/proxy-ca.crt"
cat >"${CONTEXT}/Dockerfile" <<EOF
FROM ${BASE_FROM}
COPY proxy-ca.crt /usr/local/share/ca-certificates/proxy-ca.crt
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    UV_SYSTEM_CERTS=1
EOF

docker build -t "${TAG}" "${CONTEXT}"
echo "built ${TAG} from ${BASE_FROM} with ${CA_BUNDLE} added to the trust store"
