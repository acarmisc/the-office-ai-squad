#!/usr/bin/env bash
# HTTP smoke test for the six agents, run against the offline fake LLM.
#
# Usage: scripts/smoke_test.sh compose|k8s
#   compose  agents on http://localhost:8081 (michael) to 8086 (pam), see deploy/compose.yaml
#   k8s      base URL per agent from SMOKE_BASE_URL_<AGENT>, set by deploy/kind/kind-smoke.sh
#
# Per agent: GET /ping, wait for GET /ready, then POST /invocations with post=false.
# An agent passes when /invocations answers 200 with status "complete", the agent field
# matches, and nothing was posted to an external system (scripts/smoke_check.py).
# Exits 1 if any agent fails.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="${SCRIPT_DIR}/smoke_check.py"
AGENTS=(michael jim angela dwight darryl pam)
COMPOSE_FIRST_PORT=8081
PAYLOAD='{"prompt":"smoke test","post":false}'
READY_TIMEOUT="${SMOKE_READY_TIMEOUT:-90}"
MODE="${1:-}"

if [[ "${MODE}" != "compose" && "${MODE}" != "k8s" ]]; then
  echo "usage: $0 compose|k8s" >&2
  exit 2
fi
for tool in curl python3; do
  command -v "${tool}" >/dev/null || { echo "error: ${tool} is required" >&2; exit 2; }
done

WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT
FAILURES=()

# Prints the base URL of an agent. Empty when k8s mode has no URL for it.
base_url_for() {
  local agent="$1" index var
  if [[ "${MODE}" == "compose" ]]; then
    for index in "${!AGENTS[@]}"; do
      if [[ "${AGENTS[${index}]}" == "${agent}" ]]; then
        echo "http://localhost:$((COMPOSE_FIRST_PORT + index))"
      fi
    done
    return
  fi
  var="SMOKE_BASE_URL_$(tr '[:lower:]' '[:upper:]' <<<"${agent}")"
  echo "${!var:-}"
}

fail() {
  echo "FAIL $*" >&2
  FAILURES+=("$*")
}

# Prints the HTTP status code (000 when the connection fails) and stores the body in $1.
http_code() {
  local out="$1" code
  shift
  code="$(curl --noproxy '*' -sS --max-time 120 -o "${out}" -w '%{http_code}' "$@" 2>>"${WORKDIR}/curl.err")" || true
  echo "${code:-000}"
}

wait_ready() {
  local base="$1" deadline code
  deadline=$((SECONDS + READY_TIMEOUT))
  while true; do
    code="$(http_code "${WORKDIR}/ready.body" "${base}/ready")"
    if [[ "${code}" == "200" ]]; then
      return 0
    fi
    if ((SECONDS >= deadline)); then
      return 1
    fi
    sleep 2
  done
}

check_ping() {
  local agent="$1" base="$2" code
  code="$(http_code "${WORKDIR}/${agent}.ping" "${base}/ping")"
  if [[ "${code}" != "200" ]]; then
    fail "${agent}: GET /ping returned ${code}"
    return 1
  fi
  if ! python3 -I "${CHECK}" ping "${WORKDIR}/${agent}.ping" >/dev/null 2>"${WORKDIR}/${agent}.err"; then
    fail "${agent}: GET /ping: $(cat "${WORKDIR}/${agent}.err")"
    return 1
  fi
}

check_invocation() {
  local agent="$1" base="$2" code summary
  code="$(http_code "${WORKDIR}/${agent}.invoke" -X POST \
    -H 'content-type: application/json' --data "${PAYLOAD}" "${base}/invocations")"
  if [[ "${code}" != "200" ]]; then
    fail "${agent}: POST /invocations returned ${code}: $(head -c 300 "${WORKDIR}/${agent}.invoke" 2>/dev/null || true)"
    return 1
  fi
  if summary="$(python3 -I "${CHECK}" invocation "${WORKDIR}/${agent}.invoke" "${agent}" 2>"${WORKDIR}/${agent}.err")"; then
    echo "PASS ${agent}: ${summary}"
  else
    fail "${agent}: $(cat "${WORKDIR}/${agent}.err")"
    return 1
  fi
}

check_agent() {
  local agent="$1" base
  base="$(base_url_for "${agent}")"
  if [[ -z "${base}" ]]; then
    fail "${agent}: no base URL (set SMOKE_BASE_URL_$(tr '[:lower:]' '[:upper:]' <<<"${agent}"))"
    return
  fi
  echo "--- ${agent} ${base}"
  if ! wait_ready "${base}"; then
    fail "${agent}: GET /ready did not return 200 within ${READY_TIMEOUT}s"
    return 0
  fi
  check_ping "${agent}" "${base}" || return 0
  check_invocation "${agent}" "${base}" || true
}

for agent in "${AGENTS[@]}"; do
  check_agent "${agent}"
done

if ((${#FAILURES[@]})); then
  echo "smoke ${MODE}: ${#FAILURES[@]} failure(s) out of ${#AGENTS[@]} agents" >&2
  printf '  %s\n' "${FAILURES[@]}" >&2
  exit 1
fi
echo "smoke ${MODE}: all ${#AGENTS[@]} agents passed"
