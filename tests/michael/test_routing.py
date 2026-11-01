from __future__ import annotations

import json

from code_squad._common.config.schema import ExtraAgent, Route, RoutingConfig
from code_squad.michael.routing import add_agents, detect_stack, route

REACT_PKG = json.dumps({"dependencies": {"react": "^18.3.1"}})
NEXT_PKG = json.dumps({"devDependencies": {"next": "14.2.0"}})
PLAIN_PKG = json.dumps({"dependencies": {"left-pad": "1.3.0"}})
K8S_MANIFEST = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\n"
PLAIN_YAML = "name: docs\nsteps: []\n"


def _agents(
    changed: list[str],
    manifests: dict[str, str] | None = None,
    routing: RoutingConfig | None = None,
    extra: list[ExtraAgent] | None = None,
) -> tuple[str, ...]:
    plan = route(changed, manifests or {}, routing or RoutingConfig(), extra or [])
    return plan.agents


def test_react_app_routes_components_to_jim_and_dwight_always() -> None:
    plan = route(
        ["src/App.tsx", "src/api/client.ts"],
        {"package.json": REACT_PKG},
        RoutingConfig(),
    )
    assert plan.agents == ("jim", "dwight")
    assert plan.reasons["jim"] == [
        "src/App.tsx matches **/*.tsx",
        "src/api/client.ts matches **/*.ts",
    ]
    assert plan.reasons["dwight"] == ["always run"]
    assert plan.ambiguous is False
    assert "react" in plan.stacks


def test_typescript_without_react_dependencies_is_not_routed_to_jim() -> None:
    plan = route(["lib/index.ts"], {"package.json": PLAIN_PKG}, RoutingConfig())
    assert plan.agents == ("dwight",)
    assert plan.ambiguous is True


def test_next_dependency_counts_as_react() -> None:
    assert detect_stack(["pages/index.jsx"], {"package.json": NEXT_PKG}) >= {"react"}


def test_spring_app_routes_java_to_angela() -> None:
    plan = route(
        ["src/main/java/com/example/OrderService.java", "pom.xml"],
        {"pom.xml": "<project/>"},
        RoutingConfig(),
    )
    assert plan.agents == ("angela", "dwight")
    assert plan.reasons["angela"] == [
        "src/main/java/com/example/OrderService.java matches **/*.java",
        "pom.xml matches **/pom.xml",
    ]
    assert "java" in plan.stacks


def test_kotlin_and_gradle_route_to_angela() -> None:
    assert _agents(["app/build.gradle.kts"]) == ("angela", "dwight")
    assert _agents(["src/Main.kt"]) == ("angela", "dwight")


def test_ci_only_change_routes_to_darryl() -> None:
    plan = route(
        [".gitlab-ci.yml", ".github/workflows/release.yml"], {}, RoutingConfig()
    )
    assert plan.agents == ("darryl", "dwight")
    assert plan.ambiguous is False
    assert "ci" in plan.stacks


def test_docker_and_terraform_route_to_darryl() -> None:
    assert _agents(["services/api/Dockerfile.prod"]) == ("darryl", "dwight")
    assert _agents(["compose.dev.yml"]) == ("darryl", "dwight")
    assert _agents(["infra/main.tf"]) == ("darryl", "dwight")


def test_kubernetes_manifest_is_detected_from_content() -> None:
    plan = route(
        ["k8s/web.yaml"],
        {"k8s/web.yaml": K8S_MANIFEST},
        RoutingConfig(routes=[]),
    )
    assert plan.agents == ("darryl", "dwight")
    assert "k8s" in plan.stacks
    assert plan.reasons["darryl"][0].startswith("k8s/web.yaml: Kubernetes manifest")


def test_plain_yaml_without_kubernetes_keys_is_not_routed() -> None:
    plan = route(["docs/steps.yaml"], {"docs/steps.yaml": PLAIN_YAML}, RoutingConfig())
    assert plan.agents == ("dwight",)
    assert plan.ambiguous is True


def test_mixed_change_runs_every_matching_specialist_once() -> None:
    plan = route(
        [
            "src/App.tsx",
            "src/main/java/Api.java",
            ".gitlab-ci.yml",
            "charts/web/values.yaml",
        ],
        {"package.json": REACT_PKG},
        RoutingConfig(),
    )
    assert plan.agents == ("jim", "angela", "darryl", "dwight")
    assert plan.ambiguous is False


def test_docs_only_change_is_ambiguous_and_runs_only_always_run_agents() -> None:
    plan = route(
        ["docs/guide.md", "README.md"], {"package.json": REACT_PKG}, RoutingConfig()
    )
    assert plan.agents == ("dwight",)
    assert plan.ambiguous is True


def test_empty_change_is_not_ambiguous() -> None:
    plan = route([], {}, RoutingConfig())
    assert plan.agents == ("dwight",)
    assert plan.ambiguous is False


def test_disabled_agents_are_removed_even_when_always_run() -> None:
    plan = route(
        ["src/App.tsx"],
        {"package.json": REACT_PKG},
        RoutingConfig(),
        disabled={"jim", "dwight"},
    )
    assert plan.agents == ()


def test_extra_agent_is_routed_by_its_globs() -> None:
    oscar = ExtraAgent(
        id="oscar",
        description="Python reviewer.",
        prompt_path="/etc/squad/agents/oscar/prompt.md",
        routes=["**/*.py"],
    )
    plan = route(["app/service.py"], {}, RoutingConfig(), [oscar])
    assert plan.agents == ("oscar", "dwight")
    assert plan.reasons["oscar"] == ["app/service.py matches an extra agent route"]


def test_configured_routes_extend_the_defaults() -> None:
    routing = RoutingConfig(
        routes=[
            *RoutingConfig().routes,
            Route(glob="**/*.vue", agents=["jim"], requires=["react"]),
        ]
    )
    plan = route(["web/Card.vue"], {"package.json": REACT_PKG}, routing)
    assert plan.agents == ("jim", "dwight")


def test_required_stack_must_be_present_for_a_configured_route() -> None:
    routing = RoutingConfig(
        routes=[Route(glob="**/*.vue", agents=["jim"], requires=["react"])],
        always_run=[],
    )
    assert _agents(["web/Card.vue"], {}, routing) == ()


def test_configured_always_run_list_replaces_dwight() -> None:
    routing = RoutingConfig(always_run=["darryl"])
    assert _agents(["docs/a.md"], {}, routing) == ("darryl",)


def test_add_agents_respects_known_and_disabled() -> None:
    plan = route(["docs/a.md"], {}, RoutingConfig())
    extended = add_agents(
        plan,
        ["darryl", "unknown", "jim"],
        reason="classifier",
        known={"jim", "darryl", "dwight"},
        disabled={"jim"},
    )
    assert extended.agents == ("dwight", "darryl")
    assert extended.reasons["darryl"] == ["classifier"]
