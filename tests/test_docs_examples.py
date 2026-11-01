"""Validate the examples embedded in docs/ and the consumer examples under examples/.

A fenced block directly preceded by one of these markers is validated:

- ``<!-- validate: config -->``: a repository file (RepoConfig), checked against the
  restricted-layer rules as a repository layer over the built-in defaults.
- ``<!-- validate: config:org -->``: an organisation file (SquadConfig).
- ``<!-- validate: projects -->``: a project registry file (ProjectsFile).
- ``<!-- validate: invocation -->``: a request body (InvocationRequest, JSON).
- ``<!-- validate: helm-values -->``: a values overlay, merged over values.yaml and
  checked against the chart's values.schema.json.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import jsonschema
import pytest
import yaml
from pydantic import ValidationError

from code_squad._common.config.merge import check_restricted
from code_squad._common.config.schema import (
    ProjectsFile,
    RepoConfig,
    SquadConfig,
    SquadFields,
)
from code_squad._common.contract import InvocationRequest

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
DOCS: Final[Path] = ROOT / "docs"
EXAMPLES: Final[Path] = ROOT / "examples"
CHART: Final[Path] = ROOT / "deploy" / "helm" / "code-squad"
_MARKER: Final = re.compile(
    r"^<!-- validate: (config:org|config|projects|invocation|helm-values) -->$"
)
_REQUIRED_KINDS: Final = frozenset(
    {"config", "config:org", "invocation", "helm-values"}
)
_SCHEMA_HINT: Final = "# yaml-language-server: $schema="


@dataclass(frozen=True)
class DocBlock:
    path: Path
    line: int
    kind: str
    language: str
    text: str

    @property
    def label(self) -> str:
        return f"{self.path.relative_to(ROOT)}:{self.line} [{self.kind}]"


def extract_blocks(path: Path) -> list[DocBlock]:
    lines = path.read_text(encoding="utf-8").split("\n")
    blocks: list[DocBlock] = []
    for index, raw in enumerate(lines):
        match = _MARKER.match(raw.strip())
        if match is None:
            continue
        fence_at = index + 1
        if fence_at >= len(lines) or not lines[fence_at].startswith("```"):
            raise AssertionError(
                f"{path}:{index + 1}: validate marker must be followed by a fence"
            )
        body: list[str] = []
        cursor = fence_at + 1
        while cursor < len(lines) and not lines[cursor].startswith("```"):
            body.append(lines[cursor])
            cursor += 1
        if cursor >= len(lines):
            raise AssertionError(f"{path}:{fence_at + 1}: unclosed fenced block")
        blocks.append(
            DocBlock(
                path=path,
                line=fence_at + 1,
                kind=match.group(1),
                language=lines[fence_at][3:].strip(),
                text="\n".join(body),
            )
        )
    return blocks


def all_doc_blocks() -> list[DocBlock]:
    found: list[DocBlock] = []
    for path in sorted(DOCS.rglob("*.md")):
        found.extend(extract_blocks(path))
    return found


def _load_yaml(text: str) -> Any:
    return yaml.safe_load(text)


def _json_safe(raw: Any) -> Any:
    """YAML timestamps are dates; JSON Schema sees them as ISO strings."""
    return json.loads(json.dumps(raw, default=str))


def _deep_merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged: dict[str, Any] = dict(base)
        for key, value in overlay.items():
            merged[key] = _deep_merge(base.get(key), value) if key in base else value
        return merged
    return overlay


def _chart_values() -> dict[str, Any]:
    loaded = _load_yaml((CHART / "values.yaml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _values_schema() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (CHART / "values.schema.json").read_text(encoding="utf-8")
    )
    return loaded


def validate_block(block: DocBlock) -> None:
    if block.kind == "invocation":
        InvocationRequest.model_validate(json.loads(block.text))
        return
    raw = _load_yaml(block.text)
    assert isinstance(raw, dict), f"{block.label}: block must be a mapping"
    if block.kind == "config:org":
        SquadConfig.model_validate(raw)
    elif block.kind == "projects":
        ProjectsFile.model_validate(raw)
    elif block.kind == "config":
        repo = RepoConfig.model_validate(raw)
        overlay = repo.model_dump(mode="json", exclude_unset=True)
        overlay.pop("extends", None)
        base = SquadFields().model_dump(mode="json")
        violations = check_restricted(base, overlay, "repo")
        assert not violations, f"{block.label}: {[str(item) for item in violations]}"
    elif block.kind == "helm-values":
        merged = _deep_merge(_chart_values(), raw)
        jsonschema.validate(_json_safe(merged), _values_schema())
    else:  # pragma: no cover - the regex admits only the kinds above
        raise AssertionError(f"unknown kind {block.kind}")


BLOCKS: Final[list[DocBlock]] = all_doc_blocks()


@pytest.mark.parametrize("block", BLOCKS, ids=lambda item: item.label)
def test_documented_block_validates(block: DocBlock) -> None:
    if block.kind == "invocation":
        assert block.language == "json", block.label
    else:
        assert block.language == "yaml", block.label
    validate_block(block)


def test_docs_contain_validated_blocks_of_every_kind() -> None:
    assert BLOCKS, "no validate markers found under docs/"
    kinds = {block.kind for block in BLOCKS}
    assert kinds >= _REQUIRED_KINDS, f"missing kinds: {sorted(_REQUIRED_KINDS - kinds)}"


def test_invalid_repo_block_is_rejected() -> None:
    bad = DocBlock(
        path=DOCS / "x.md",
        line=1,
        kind="config",
        language="yaml",
        text="vcs:\n  provider: github\n",
    )
    with pytest.raises(AssertionError):
        validate_block(bad)


def test_invalid_invocation_block_is_rejected() -> None:
    bad = DocBlock(
        path=DOCS / "x.md",
        line=1,
        kind="invocation",
        language="json",
        text='{"prompt": "x", "unknown": 1}',
    )
    with pytest.raises(ValidationError):
        validate_block(bad)


def test_helm_block_is_checked_against_the_schema() -> None:
    bad = DocBlock(
        path=DOCS / "x.md",
        line=1,
        kind="helm-values",
        language="yaml",
        text="agents:\n  intruder:\n    enabled: true\n",
    )
    with pytest.raises(jsonschema.ValidationError):
        validate_block(bad)


@pytest.mark.parametrize(
    "path",
    sorted((CHART / "values-examples").glob("*.yaml")),
    ids=lambda p: p.name,
)
def test_values_examples_validate_against_the_schema(path: Path) -> None:
    overlay = _load_yaml(path.read_text(encoding="utf-8"))
    merged = _deep_merge(_chart_values(), overlay)
    jsonschema.validate(_json_safe(merged), _values_schema())


def _gitlab() -> Path:
    return EXAMPLES / "gitlab" / "gitlab-ci-snippet.yml"


def _github_workflow() -> Path:
    return EXAMPLES / "github" / "github-actions-workflow.yml"


def _manifest() -> Path:
    return EXAMPLES / "github" / "github-app-manifest.json"


def test_gitlab_snippet_starts_with_the_schema_hint() -> None:
    first = _gitlab().read_text(encoding="utf-8").split("\n", 1)[0]
    assert first == (
        "# yaml-language-server: $schema="
        "https://gitlab.com/gitlab-org/gitlab/-/raw/master/app/assets/javascripts/"
        "editor/schema/ci.json"
    )


def test_gitlab_snippet_runs_on_merge_request_events_and_calls_michael() -> None:
    job = _load_yaml(_gitlab().read_text(encoding="utf-8"))["squad-review"]
    rules = [rule["if"] for rule in job["rules"]]
    assert '$CI_PIPELINE_SOURCE == "merge_request_event"' in rules
    script = "\n".join(str(line) for line in job["script"])
    assert "/invocations" in script
    assert job["variables"]["SQUAD_POST"] == "false"
    assert "SQUAD_POST" in script


def test_github_workflow_starts_with_the_schema_hint() -> None:
    first = _github_workflow().read_text(encoding="utf-8").split("\n", 1)[0]
    assert first == (f"{_SCHEMA_HINT}https://json.schemastore.org/github-workflow.json")


def test_github_workflow_has_minimal_permissions_and_no_risky_trigger() -> None:
    text = _github_workflow().read_text(encoding="utf-8")
    workflow = _load_yaml(text)
    assert workflow["permissions"] == {"contents": "read"}
    triggers = workflow.get(True, workflow.get("on"))
    assert "pull_request" in triggers
    assert "pull_request_target" not in triggers
    assert "pull_request_target" not in text


def test_github_workflow_pins_every_action_to_a_commit_sha() -> None:
    text = _github_workflow().read_text(encoding="utf-8")
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", text, flags=re.MULTILINE)
    for reference in uses:
        assert re.search(r"@[0-9a-f]{40}$", reference), reference


def test_github_app_manifest_permissions_are_exactly_the_documented_set() -> None:
    manifest: dict[str, Any] = json.loads(_manifest().read_text(encoding="utf-8"))
    assert manifest["default_permissions"] == {
        "metadata": "read",
        "contents": "write",
        "pull_requests": "write",
        "issues": "write",
        "checks": "write",
        "statuses": "write",
        "actions": "read",
    }


def test_github_app_manifest_events_are_exactly_the_documented_set() -> None:
    manifest: dict[str, Any] = json.loads(_manifest().read_text(encoding="utf-8"))
    events = manifest["default_events"]
    assert sorted(events) == sorted(
        ["pull_request", "issue_comment", "pull_request_review_comment", "issues"]
    )
    assert len(events) == len(set(events))


def test_github_app_manifest_keeps_the_webhook_on_the_documented_path() -> None:
    manifest: dict[str, Any] = json.loads(_manifest().read_text(encoding="utf-8"))
    assert manifest["hook_attributes"]["url"].endswith("/webhooks/github")
    assert manifest["hook_attributes"]["active"] is True


def test_no_example_block_contains_a_real_looking_secret() -> None:
    patterns = [
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
        re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ]
    for path in [_gitlab(), _github_workflow(), _manifest()]:
        for pattern in patterns:
            assert not pattern.search(path.read_text(encoding="utf-8")), path.name


def test_validation_does_not_mutate_the_chart_defaults() -> None:
    before = copy.deepcopy(_chart_values())
    _deep_merge(_chart_values(), {"llm": {"baseUrl": "https://llm.example.com"}})
    assert _chart_values() == before
