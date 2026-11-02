"""Structure of .github/workflows/release.yml and the chart defaults it publishes to."""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Final

import yaml

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
WORKFLOW: Final[Path] = ROOT / ".github" / "workflows" / "release.yml"
VALUES: Final[Path] = ROOT / "deploy" / "helm" / "code-squad" / "values.yaml"
_USES: Final = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)", re.MULTILINE)
_SHA_PIN: Final = re.compile(r"@[0-9a-f]{40}\s+#\s*v\d")
_SEMVER_LINE: Final = re.compile(r"^\s*semver='(.+)'\s*$", re.MULTILINE)


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict[Any, Any]:
    data = yaml.safe_load(_text())
    assert isinstance(data, dict)
    return data


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML follows YAML 1.1 and reads the bare key `on` as the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _job(name: str) -> dict[str, Any]:
    job = _workflow()["jobs"][name]
    assert isinstance(job, dict)
    return job


def _steps(name: str) -> list[dict[str, Any]]:
    steps = _job(name)["steps"]
    assert isinstance(steps, list)
    return steps


def _run_lines(name: str) -> list[str]:
    lines: list[str] = []
    for step in _steps(name):
        lines.extend(str(step.get("run", "")).splitlines())
    return [line.strip() for line in lines]


def _step(name: str, uses_prefix: str) -> dict[str, Any]:
    for step in _steps(name):
        if str(step.get("uses", "")).startswith(uses_prefix):
            return step
    raise AssertionError(f"job {name!r} has no step using {uses_prefix!r}")


def test_tag_trigger_matches_semver_tags_and_dispatch_takes_a_tag() -> None:
    triggers = _triggers(_workflow())
    assert triggers["push"]["tags"] == ["v*.*.*"]
    dispatch_input = triggers["workflow_dispatch"]["inputs"]["tag"]
    assert dispatch_input["required"] is True
    assert dispatch_input["type"] == "string"


def test_semver_check_accepts_release_and_prerelease_tags_only() -> None:
    match = _SEMVER_LINE.search(_text())
    assert match is not None
    pattern = re.compile(match.group(1))
    for accepted in ("v0.1.0", "v10.20.30", "v0.2.0-rc.1"):
        assert pattern.fullmatch(accepted), accepted
    for rejected in ("0.1.0", "v1.2", "v01.2.3", "v1.2.3.4", "v1.2.3-"):
        assert pattern.fullmatch(rejected) is None, rejected


def test_top_level_permissions_are_empty() -> None:
    assert _workflow()["permissions"] == {}


def test_job_permissions_are_least_privilege() -> None:
    expected: dict[str, dict[str, str]] = {
        "verify": {"contents": "read"},
        "images": {
            "contents": "read",
            "packages": "write",
            "id-token": "write",
            "attestations": "write",
        },
        "chart": {"contents": "read", "packages": "write"},
        "release": {"contents": "write"},
        "create-tag": {"contents": "write"},
    }
    for name, permissions in expected.items():
        assert _job(name)["permissions"] == permissions, name
    writers = [
        name
        for name, job in _workflow()["jobs"].items()
        if job["permissions"].get("contents") == "write"
    ]
    assert sorted(writers) == ["create-tag", "release"]


def test_concurrency_is_per_tag_and_never_cancels() -> None:
    concurrency = _workflow()["concurrency"]
    assert "release-" in concurrency["group"]
    assert "inputs.tag" in concurrency["group"]
    assert concurrency["cancel-in-progress"] is False


def test_jobs_run_in_order_verify_images_chart_release() -> None:
    jobs = _workflow()["jobs"]

    def needs(name: str) -> list[str]:
        value = jobs[name].get("needs", [])
        return [value] if isinstance(value, str) else list(value)

    assert needs("create-tag") == []
    assert needs("verify") == ["create-tag"]
    assert needs("images") == ["verify"]
    assert set(needs("chart")) == {"verify", "images"}
    assert set(needs("release")) == {"verify", "images", "chart"}


def test_matrix_builds_both_images_from_their_dockerfiles() -> None:
    include = _job("images")["strategy"]["matrix"]["include"]
    pairs = {(entry["image"], entry["dockerfile"]) for entry in include}
    assert pairs == {
        ("code-squad", "deploy/Dockerfile"),
        ("code-squad-sandbox-node", "deploy/sandbox-node.Dockerfile"),
    }
    for _, dockerfile in pairs:
        assert (ROOT / dockerfile).is_file(), dockerfile


def test_images_are_built_for_amd64_and_arm64_with_provenance_and_sbom() -> None:
    build = _step("images", "docker/build-push-action@")["with"]
    platforms = set(str(build["platforms"]).split(","))
    assert {"linux/amd64", "linux/arm64"} <= platforms
    assert build["push"] is True
    assert build["provenance"] == "mode=max"
    assert build["sbom"] is True


def test_latest_tag_is_only_published_for_stable_releases() -> None:
    tags = str(_step("images", "docker/metadata-action@")["with"]["tags"])
    lines = [line.strip() for line in tags.splitlines() if line.strip()]
    latest = [line for line in lines if "value=latest" in line]
    assert len(latest) == 1
    assert "enable=${{ needs.verify.outputs.prerelease == 'false' }}" in latest[0]
    assert any("{{version}}" in line for line in lines)
    assert any("{{major}}.{{minor}}" in line for line in lines)
    assert any(line.startswith("type=raw,value=sha-") for line in lines)


def test_image_labels_cover_source_revision_version_license_and_description() -> None:
    labels = str(_step("images", "docker/metadata-action@")["with"]["labels"])
    for key in (
        "org.opencontainers.image.source",
        "org.opencontainers.image.revision",
        "org.opencontainers.image.version",
        "org.opencontainers.image.licenses",
        "org.opencontainers.image.description",
    ):
        assert f"{key}=" in labels, key


def test_image_names_are_lowercased_before_use() -> None:
    lowering = [step for step in _steps("images") if step.get("id") == "owner"]
    assert lowering, "no step computes the lowercase image name"
    assert ",," in str(lowering[0]["run"])


def test_verify_job_runs_the_full_gate() -> None:
    assert "just check" in _run_lines("verify")


def test_verify_checks_the_version_against_the_sources() -> None:
    text = _text()
    for source in ("pyproject.toml", "Chart.yaml", "src/code_squad/__init__.py"):
        assert source in text, source
    assert "scripts/bump_image.py" in text


def test_every_action_is_pinned_to_a_sha_or_marked_todo() -> None:
    lines = _text().splitlines()
    uses_lines = [line for line in lines if _USES.match(line)]
    assert uses_lines
    for line in uses_lines:
        if _SHA_PIN.search(line):
            continue
        assert "TODO: pin" in line, line


def test_chart_is_packaged_with_the_tag_version_and_pushed_to_ghcr_oci() -> None:
    run = _run_lines("chart")
    assert any(
        line.startswith("helm package ")
        and "--version" in line
        and "--app-version" in line
        for line in run
    )
    assert any("helm registry login ghcr.io" in line for line in run)
    assert any(
        line.startswith("helm push ") and "oci://ghcr.io/" in line and "/charts" in line
        for line in run
    )
    assert any(
        step.get("uses", "").startswith("actions/upload-artifact@")
        and step["with"]["name"] == "chart"
        for step in _steps("chart")
    )


def test_release_extracts_changelog_notes_and_attaches_assets() -> None:
    run_text = "\n".join(_run_lines("release"))
    assert "## [" in run_text
    assert "--generate-notes" in run_text
    assert "--prerelease" in run_text
    assert "images.txt" in run_text
    assert "code-squad-*.tgz" in run_text


def test_chart_defaults_point_at_ghcr_and_tag_follows_app_version() -> None:
    values = yaml.safe_load(VALUES.read_text(encoding="utf-8"))
    assert values["image"]["repository"] == "ghcr.io/acarmisc/code-squad"
    assert values["image"]["tag"] == ""
    sandbox_image = values["sandbox"]["image"]
    assert sandbox_image.startswith("ghcr.io/acarmisc/code-squad-sandbox-node:")


def _verify_script() -> str:
    lines = _text().splitlines()
    start = next(
        i for i, line in enumerate(lines) if "uv run --frozen python -" in line
    )
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() == "PY":
            return textwrap.dedent("\n".join(body)) + "\n"
        body.append(line)
    raise AssertionError("the version check heredoc is not closed")


def _run_verify(root: Path, version: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-", version],
        input=_verify_script(),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_version_check_passes_on_the_repository_sources() -> None:
    version = yaml.safe_load(
        (ROOT / "deploy" / "helm" / "code-squad" / "Chart.yaml").read_text("utf-8")
    )["appVersion"]
    completed = _run_verify(ROOT, str(version))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "action.yml" in completed.stdout


def test_version_check_fails_when_the_action_image_tag_is_stale(tmp_path: Path) -> None:
    for source in ("pyproject.toml", "action.yml"):
        (tmp_path / source).write_text((ROOT / source).read_text("utf-8"), "utf-8")
    chart = tmp_path / "deploy" / "helm" / "code-squad"
    chart.mkdir(parents=True)
    (chart / "Chart.yaml").write_text(
        (ROOT / "deploy" / "helm" / "code-squad" / "Chart.yaml").read_text("utf-8"),
        "utf-8",
    )
    package = tmp_path / "src" / "code_squad"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        (ROOT / "src" / "code_squad" / "__init__.py").read_text("utf-8"), "utf-8"
    )
    stale = (
        (ROOT / "action.yml")
        .read_text("utf-8")
        .replace("code-squad:", "code-squad:0.0.9-stale-")
    )
    (tmp_path / "action.yml").write_text(stale, "utf-8")
    version = yaml.safe_load((chart / "Chart.yaml").read_text("utf-8"))["appVersion"]
    completed = _run_verify(tmp_path, str(version))
    assert completed.returncode == 1
    assert "action.yml inputs.image default tag" in completed.stdout


def test_create_tag_only_runs_on_dispatch_from_main_and_never_overwrites() -> None:
    job = _job("create-tag")
    assert "workflow_dispatch" in job["if"] and "inputs.create_tag" in job["if"]
    script = "\n".join(step.get("run", "") for step in job["steps"])
    assert "refs/heads/main" in script
    assert "already exists" in script
    assert 'git push origin "refs/tags/$TAG"' in script
    assert "--force" not in script
    verify_if = _job("verify")["if"]
    assert "skipped" in verify_if and "success" in verify_if
