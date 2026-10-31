#!/usr/bin/env bash
# Create the local kind cluster, build and load the image, deploy the fake LLM and install the chart
# with values-examples/minimal-kind.yaml.
#
# Requires kind, kubectl, helm and docker on PATH. Overrides: CLUSTER_NAME, NAMESPACE.
# The image tag is fixed to code-squad:dev, matching minimal-kind.yaml.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-code-squad}"
NAMESPACE="${NAMESPACE:-code-squad}"
IMAGE="code-squad:dev"
CHART_DIR="${REPO_ROOT}/deploy/helm/code-squad"
VALUES_FILE="${CHART_DIR}/values-examples/minimal-kind.yaml"

for tool in kind kubectl helm docker; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "error: ${tool} is not on PATH" >&2
    exit 1
  fi
done

existing_clusters="$(kind get clusters)"
if grep -qx "${CLUSTER_NAME}" <<<"${existing_clusters}"; then
  echo "kind cluster ${CLUSTER_NAME} already exists, reusing it"
else
  kind create cluster --name "${CLUSTER_NAME}" --config "${SCRIPT_DIR}/kind-config.yaml" --wait 120s
fi

docker build -f "${REPO_ROOT}/deploy/Dockerfile" -t "${IMAGE}" "${REPO_ROOT}"
kind load docker-image "${IMAGE}" --name "${CLUSTER_NAME}"

kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

# Demo-only key for the fake LLM. It has no value outside this local cluster.
kubectl -n "${NAMESPACE}" create secret generic code-squad-secrets \
  --from-literal=llm-api-key=fake-key-for-local-demo \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n "${NAMESPACE}" apply -f "${SCRIPT_DIR}/fake-llm.yaml"
kubectl -n "${NAMESPACE}" rollout status deployment/fake-llm --timeout=180s

helm upgrade --install code-squad "${CHART_DIR}" \
  --namespace "${NAMESPACE}" \
  --values "${VALUES_FILE}" \
  --wait --timeout 5m

kubectl -n "${NAMESPACE}" get deploy,svc
echo "Ready. Run deploy/kind/kind-smoke.sh to exercise the agents."
