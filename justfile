set shell := ["bash", "-euo", "pipefail", "-c"]
export NO_MKDOCS_2_WARNING := "1"

image := env_var_or_default("IMAGE", "code-squad")
tag := `git rev-parse --short HEAD 2>/dev/null || echo dev`

default: check

# Full quality gate (identical in GitLab CI and GitHub Actions).
check: lint typecheck test prompts docs-check docs helm-lint secret-scan

lint:
    uv run ruff check .
    uv run ruff format --check .

fmt:
    uv run ruff check --fix .
    uv run ruff format .

typecheck:
    uv run mypy src tests scripts eval deploy

test *args:
    uv run pytest {{args}}

prompts:
    uv run python scripts/check_prompts.py

docs-gen *args:
    uv run python scripts/gen_schemas.py {{args}}
    uv run python scripts/gen_docs.py {{args}}

docs-check:
    just docs-gen --check

docs:
    uv run mkdocs build --strict --site-dir site

secret-scan:
    uv run python scripts/secret_scan.py

helm-lint:
    #!/usr/bin/env bash
    set -euo pipefail
    chart=deploy/helm/code-squad
    if [ ! -d "$chart" ]; then echo "no chart yet"; exit 0; fi
    helm lint "$chart"
    for f in "$chart"/values.yaml "$chart"/values-examples/*.yaml; do
      [ -f "$f" ] || continue
      helm lint "$chart" -f "$f" >/dev/null
      helm template t "$chart" -f "$f" | kubeconform -strict -summary -ignore-missing-schemas
    done

build:
    docker buildx build --platform linux/amd64,linux/arm64 -f deploy/Dockerfile -t {{image}}:{{tag}} .

build-native:
    docker build -f deploy/Dockerfile -t {{image}}:{{tag}} .

run-local agent:
    AGENT_NAME={{agent}} uv run uvicorn code_squad.server:app --host 0.0.0.0 --port 8080

invoke agent prompt url="http://localhost:8080":
    curl -sS -X POST {{url}}/invocations -H 'content-type: application/json' \
      ${SQUAD_API_TOKEN:+-H "authorization: Bearer ${SQUAD_API_TOKEN}"} \
      -d "$(jq -n --arg p '{{prompt}}' '{prompt:$p, post:false}')"

kind-up:
    deploy/kind/kind-up.sh

kind-smoke:
    deploy/kind/kind-smoke.sh

compose-smoke:
    scripts/smoke_test.sh compose

eval *args:
    uv run python -m eval.run {{args}}
