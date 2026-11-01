#!/usr/bin/env bash
# Port-forward every agent Service and run scripts/smoke_test.sh in k8s mode against them.
# Each agent is reachable through SMOKE_BASE_URL_<AGENT> (for example SMOKE_BASE_URL_MICHAEL).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
NAMESPACE="${NAMESPACE:-code-squad}"
FIRST_LOCAL_PORT="${FIRST_LOCAL_PORT:-18080}"
AGENTS=(michael jim angela dwight darryl pam)

PF_PIDS=()
cleanup() {
  for pid in ${PF_PIDS[@]+"${PF_PIDS[@]}"}; do
    kill "${pid}" 2>/dev/null || true
  done
}
trap cleanup EXIT

if [[ ! -x "${REPO_ROOT}/scripts/smoke_test.sh" ]]; then
  echo "error: ${REPO_ROOT}/scripts/smoke_test.sh is missing or not executable" >&2
  exit 1
fi

port="${FIRST_LOCAL_PORT}"
for agent in "${AGENTS[@]}"; do
  kubectl -n "${NAMESPACE}" port-forward "svc/code-squad-${agent}" "${port}:8080" >/dev/null 2>&1 &
  PF_PIDS+=("$!")
  var="SMOKE_BASE_URL_$(tr '[:lower:]' '[:upper:]' <<<"${agent}")"
  export "${var}=http://127.0.0.1:${port}"
  port=$((port + 1))
done

# Wait until every agent answers /ready, or fail after about 60 seconds.
port="${FIRST_LOCAL_PORT}"
for agent in "${AGENTS[@]}"; do
  ready=0
  for _ in $(seq 1 30); do
    if curl --noproxy "*" -fsS "http://127.0.0.1:${port}/ready" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  if [[ "${ready}" -ne 1 ]]; then
    echo "error: ${agent} did not become ready on port ${port}" >&2
    exit 1
  fi
  echo "ready: ${agent}"
  port=$((port + 1))
done

"${REPO_ROOT}/scripts/smoke_test.sh" k8s
