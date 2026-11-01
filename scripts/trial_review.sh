#!/usr/bin/env bash
# Run one review of a change request through michael and print the result.
#
# Usage: scripts/trial_review.sh <michael-base-url> <project> <change-request-number> [--post]
#
# Dry run by default (post=false): nothing is written to the VCS. --post sets post=true and
# michael publishes comments and the commit status. The bearer token is read from
# SQUAD_API_TOKEN when it is set. Exit codes: 0 complete or incomplete, 1 on an HTTP error
# or a failed run, 2 on bad usage.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT="${SCRIPT_DIR}/trial_report.py"
USAGE="usage: $0 <michael-base-url> <project> <change-request-number> [--post]"

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "${USAGE}" >&2
  exit 2
fi
BASE_URL="${1%/}"
PROJECT="$2"
CR_NUMBER="$3"
POST=false
if [[ $# -eq 4 ]]; then
  if [[ "$4" != "--post" ]]; then
    echo "${USAGE}" >&2
    exit 2
  fi
  POST=true
fi
if [[ ! "${CR_NUMBER}" =~ ^[0-9]+$ ]]; then
  echo "error: change-request-number must be a number, got '${CR_NUMBER}'" >&2
  exit 2
fi
for tool in curl python3; do
  command -v "${tool}" >/dev/null || { echo "error: ${tool} is required" >&2; exit 2; }
done

if [[ "${POST}" == true ]]; then
  echo "WARNING: --post is set. michael will publish comments and the commit status to ${PROJECT} !${CR_NUMBER}." >&2
else
  echo "dry run: post=false, nothing is written to the VCS." >&2
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
KEY="trial-${PROJECT}-${CR_NUMBER}-${STAMP}"
BODY="$(python3 -I -c '
import json, sys
project, number, post, key = sys.argv[1:5]
print(json.dumps({
    "prompt": f"review change request {number}",
    "project": project,
    "target": number,
    "mode": "review",
    "post": post == "true",
    "idempotency_key": key,
}))
' "${PROJECT}" "${CR_NUMBER}" "${POST}" "${KEY}")"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT
AUTH_ARGS=()
if [[ -n "${SQUAD_API_TOKEN:-}" ]]; then
  AUTH_ARGS=(-H "authorization: Bearer ${SQUAD_API_TOKEN}")
fi

START="$(date +%s.%N)"
code="$(curl --noproxy '*' -sS --max-time 900 -o "${WORKDIR}/result.json" -w '%{http_code}' \
  -X POST "${BASE_URL}/invocations" -H 'content-type: application/json' \
  "${AUTH_ARGS[@]}" --data "${BODY}")" || code="000"
END="$(date +%s.%N)"
WALL="$(python3 -I -c 'import sys; print(float(sys.argv[2]) - float(sys.argv[1]))' "${START}" "${END}")"

if [[ "${code}" != "200" ]]; then
  echo "error: POST /invocations returned HTTP ${code}" >&2
  head -c 600 "${WORKDIR}/result.json" 2>/dev/null >&2 || true
  echo >&2
  exit 1
fi
python3 -I "${REPORT}" "${WORKDIR}/result.json" --wall-seconds "${WALL}"
