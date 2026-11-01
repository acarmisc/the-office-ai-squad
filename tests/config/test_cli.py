from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from code_squad._common.cli import app
from code_squad._common.fake_model import ScriptedModel
from code_squad._common.model import set_model_factory
from tests.config.support import write
from tests.support import finish_turn

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def scripted() -> Iterator[ScriptedModel]:
    model = ScriptedModel([finish_turn("approve", "Review done.")])
    set_model_factory(lambda *_args: model)
    yield model
    set_model_factory(None)


def test_schema_prints_the_repo_config_schema(runner: CliRunner) -> None:
    result = runner.invoke(app, ["config", "schema"])
    assert result.exit_code == 0, result.output
    schema = json.loads(result.output)
    assert "vcs" in schema["properties"]
    assert "extends" in schema["properties"]


@pytest.mark.parametrize(
    ("kind", "key"),
    [("projects", "projects"), ("invocation", "prompt"), ("finding", "rule_id")],
)
def test_schema_supports_each_kind(runner: CliRunner, kind: str, key: str) -> None:
    result = runner.invoke(app, ["config", "schema", "--kind", kind])
    assert result.exit_code == 0, result.output
    assert key in json.loads(result.output)["properties"]


def test_schema_rejects_an_unknown_kind(runner: CliRunner) -> None:
    result = runner.invoke(app, ["config", "schema", "--kind", "nonsense"])
    assert result.exit_code == 2


def test_validate_accepts_the_shipped_examples(runner: CliRunner) -> None:
    # CI workflow files under examples/gitlab and examples/github are not squad
    # configuration; tests/test_docs_examples.py validates them.
    result = runner.invoke(
        app,
        [
            "config",
            "validate",
            str(ROOT / "examples" / "org"),
            str(ROOT / "examples" / "repo"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "ok:" in result.output


def test_validate_reports_readable_errors_and_fails(
    runner: CliRunner, tmp_path: Path
) -> None:
    bad = write(tmp_path, ".squad/config.yml", "vcs:\n  provder: github\n")
    result = runner.invoke(app, ["config", "validate", str(bad)])
    assert result.exit_code == 1
    assert "config.yml" in result.output
    assert "vcs.provder" in result.output


def test_validate_detects_each_kind(runner: CliRunner, tmp_path: Path) -> None:
    files = {
        "org/squad.yaml": "review:\n  max_findings: 3\n",
        "registry/projects.yaml": "projects:\n  - match: acme/web-shop\n",
        "registry/profiles/team.yaml": "review:\n  max_findings: 4\n",
    }
    paths = [write(tmp_path, name, text) for name, text in files.items()]
    result = runner.invoke(app, ["config", "validate", *map(str, paths)])
    assert result.exit_code == 0, result.output
    assert "(org)" in result.output
    assert "(projects)" in result.output
    assert "(profile)" in result.output


def test_validate_reports_yaml_errors(runner: CliRunner, tmp_path: Path) -> None:
    bad = write(tmp_path, "squad.yaml", "review: [oops\n")
    result = runner.invoke(app, ["config", "validate", str(bad)])
    assert result.exit_code == 1
    assert "cannot read YAML" in result.output


def _org_and_registry(tmp_path: Path) -> tuple[Path, Path]:
    org = write(tmp_path, "squad.yaml", "review:\n  max_findings: 11\n")
    registry = write(
        tmp_path,
        "projects.yaml",
        "projects:\n  - match: acme/web-shop\n    provider: github\n",
    )
    return org, registry


def test_explain_json_shows_provenance(runner: CliRunner, tmp_path: Path) -> None:
    org, registry = _org_and_registry(tmp_path)
    repo = write(tmp_path, "config.yml", "review:\n  min_confidence_to_publish: low\n")
    result = runner.invoke(
        app,
        [
            "config",
            "explain",
            "acme/web-shop",
            "--org",
            str(org),
            "--projects",
            str(registry),
            "--repo-config",
            str(repo),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    rows = {row["key"]: row for row in data["effective"]}
    assert rows["review.max_findings"] == {
        "key": "review.max_findings",
        "value": 11,
        "layer": "org",
    }
    assert rows["review.min_confidence_to_publish"]["layer"] == "repo"
    assert rows["vcs.provider"]["layer"] == "registry:acme/web-shop"


def test_explain_yaml_is_the_default_format(runner: CliRunner, tmp_path: Path) -> None:
    org, registry = _org_and_registry(tmp_path)
    result = runner.invoke(
        app,
        [
            "config",
            "explain",
            "acme/web-shop",
            "--org",
            str(org),
            "--projects",
            str(registry),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "config_hash:" in result.output


def test_explain_shows_rejected_layers(runner: CliRunner, tmp_path: Path) -> None:
    repo = write(tmp_path, "config.yml", "vcs:\n  approve_mode: approve\n")
    result = runner.invoke(
        app,
        [
            "config",
            "explain",
            "acme/web-shop",
            "--repo-config",
            str(repo),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["rejected_layers"][0]["layer"] == "repo"


def test_explain_reports_a_bad_org_file(runner: CliRunner, tmp_path: Path) -> None:
    org = write(tmp_path, "squad.yaml", "review:\n  max_findings: 0\n")
    result = runner.invoke(
        app, ["config", "explain", "acme/web-shop", "--org", str(org)]
    )
    assert result.exit_code == 1
    assert "org config is invalid" in result.output


def test_explain_rejects_an_unknown_format(runner: CliRunner) -> None:
    result = runner.invoke(
        app, ["config", "explain", "acme/web-shop", "--format", "xml"]
    )
    assert result.exit_code == 2


@pytest.mark.parametrize("kind", ["react", "java", "generic"])
def test_init_prints_a_scaffold_that_starts_with_the_schema_hint(
    runner: CliRunner, kind: str
) -> None:
    result = runner.invoke(app, ["config", "init", kind])
    assert result.exit_code == 0, result.output
    first = result.output.splitlines()[0]
    assert first == (
        "# yaml-language-server: $schema=https://raw.githubusercontent.com/"
        "acarmisc/the-office-ai-squad/main/schemas/squad-config.schema.json"
    )


@pytest.mark.parametrize("kind", ["react", "java", "generic"])
def test_scaffolds_validate(runner: CliRunner, tmp_path: Path, kind: str) -> None:
    out = tmp_path / ".squad" / "config.yml"
    result = runner.invoke(app, ["config", "init", kind, "--output", str(out)])
    assert result.exit_code == 0, result.output
    check = runner.invoke(app, ["config", "validate", str(out)])
    assert check.exit_code == 0, check.output


def test_init_refuses_to_overwrite_without_force(
    runner: CliRunner, tmp_path: Path
) -> None:
    out = write(tmp_path, "config.yml", "# existing\n")
    refused = runner.invoke(app, ["config", "init", "react", "--output", str(out)])
    assert refused.exit_code == 1
    assert out.read_text() == "# existing\n"
    forced = runner.invoke(
        app, ["config", "init", "react", "--output", str(out), "--force"]
    )
    assert forced.exit_code == 0
    assert out.read_text().startswith("# yaml-language-server")


def test_init_rejects_an_unknown_kind(runner: CliRunner) -> None:
    result = runner.invoke(app, ["config", "init", "cobol"])
    assert result.exit_code == 2


def test_review_is_an_alias_for_michael(
    runner: CliRunner, scripted: ScriptedModel
) -> None:
    result = runner.invoke(
        app, ["review", "42", "--project", "acme/web-shop", "--no-post"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["agent"] == "michael"
    assert payload["status"] == "complete"


def test_review_requires_a_project(runner: CliRunner) -> None:
    result = runner.invoke(app, ["review", "42"])
    assert result.exit_code != 0


def test_validate_directory_skips_non_squad_yaml(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "ci.yml").write_text("on: push\njobs: {}\n", "utf-8")
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "config.yml").write_text("review: {}\n", "utf-8")
    result = CliRunner().invoke(app, ["config", "validate", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "ci.yml" not in result.output
    assert "config.yml" in result.output
