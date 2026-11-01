from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from code_squad._common.config.schema import SquadFields
from code_squad._common.registry import all_specs
from code_squad._common.tool_policy import TOOL_POLICY, tool_name
from code_squad._common.vcs.base import Capability

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
REFERENCE = ROOT / "docs" / "reference"
MARKER = "<!-- generated — do not edit."


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gen_docs = _load("gen_docs")
bump_image = _load("bump_image")


def test_reference_pages_match_the_code() -> None:
    rendered = gen_docs.render_all()
    assert len(rendered) == 5
    for path, text in rendered.items():
        assert path.read_text(encoding="utf-8") == text, f"drift in {path.name}"


def test_rendering_is_deterministic() -> None:
    assert gen_docs.render_all() == gen_docs.render_all()


def test_every_page_starts_with_the_generated_marker() -> None:
    for path, text in gen_docs.render_all().items():
        assert path.parent == REFERENCE
        assert text.startswith(MARKER), path.name


def test_configuration_page_documents_every_top_level_section() -> None:
    page = gen_docs.render_configuration()
    for name in SquadFields.model_fields:
        assert f"| `{name}` |" in page, name


def test_configuration_page_shows_merge_policy_and_mergeable_sets() -> None:
    page = gen_docs.render_configuration()
    approve_row = next(
        line for line in page.splitlines() if "| `approve_mode` |" in line
    )
    assert "tighten_only" in approve_row
    assert "order none, comment, approve" in approve_row
    protected_row = next(
        line for line in page.splitlines() if "| `protected_branches` |" in line
    )
    assert "mergeable set" in protected_row


def test_tool_policy_page_lists_every_exposed_tool() -> None:
    page = gen_docs.render_tool_policy()
    for spec in all_specs():
        for tool in spec.tools:
            name = tool_name(tool)
            assert f"| `{name}` |" in page, name
            assert name in TOOL_POLICY


def test_every_capability_has_a_documented_fallback() -> None:
    assert set(gen_docs._CAPABILITY_FALLBACKS) == set(Capability)
    page = gen_docs.render_vcs_capabilities()
    for capability in Capability:
        assert f"| `{capability.value}` |" in page


def _chart(tmp_path: Path) -> Path:
    source = ROOT / "deploy" / "helm" / "code-squad"
    target = tmp_path / "chart"
    target.mkdir()
    for name in ("Chart.yaml", "values.yaml"):
        (target / name).write_text(
            (source / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    return target


def test_bump_image_updates_version_appversion_and_tag(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    code = bump_image.main(
        ["--version", "1.2.3", "--tag", "sha-abc1234", "--chart-dir", str(chart)]
    )
    assert code == 0
    chart_text = (chart / "Chart.yaml").read_text(encoding="utf-8")
    assert 'version: "1.2.3"' in chart_text
    assert 'appVersion: "1.2.3"' in chart_text
    values_text = (chart / "values.yaml").read_text(encoding="utf-8")
    assert 'tag: "sha-abc1234"' in values_text
    assert "# Image tag. An empty string means Chart.appVersion" in values_text
    assert "code-squad-sandbox-node:1.2.3" in values_text


def test_bump_image_dry_run_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chart = _chart(tmp_path)
    before = {
        name: (chart / name).read_text(encoding="utf-8")
        for name in ("Chart.yaml", "values.yaml")
    }
    code = bump_image.main(
        ["--version", "2.0.0", "--tag", "v2", "--dry-run", "--chart-dir", str(chart)]
    )
    assert code == 0
    after = {name: (chart / name).read_text(encoding="utf-8") for name in before}
    assert before == after
    out = capsys.readouterr().out
    assert "dry run" in out
    assert '+version: "2.0.0"' in out


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--version", "not-a-version"],
        ["--tag", "bad tag with spaces"],
    ],
)
def test_bump_image_rejects_bad_arguments(tmp_path: Path, argv: list[str]) -> None:
    chart = _chart(tmp_path)
    assert bump_image.main([*argv, "--chart-dir", str(chart)]) == 2


def test_bump_image_refuses_a_chart_without_the_expected_keys(tmp_path: Path) -> None:
    chart = tmp_path / "chart"
    chart.mkdir()
    (chart / "Chart.yaml").write_text("name: x\n", encoding="utf-8")
    (chart / "values.yaml").write_text("image:\n  repository: r\n", encoding="utf-8")
    assert bump_image.main(["--version", "1.0.0", "--chart-dir", str(chart)]) == 2
    assert bump_image.main(["--tag", "v1", "--chart-dir", str(chart)]) == 2


def test_bump_image_version_updates_pyproject_and_package(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "code-squad"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    package = tmp_path / "src" / "code_squad"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    changes = bump_image.plan(chart, None, "0.3.0", root=tmp_path)
    for change in changes:
        change.path.write_text(change.after, encoding="utf-8")
    assert 'version = "0.3.0"' in (tmp_path / "pyproject.toml").read_text("utf-8")
    assert '__version__ = "0.3.0"' in (package / "__init__.py").read_text("utf-8")
