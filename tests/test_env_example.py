""".env.example must match the bootstrap env table (no drift)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from code_squad._common.config.bootstrap import BOOTSTRAP_ENV

REPO = Path(__file__).resolve().parent.parent
GENERATOR = REPO / "scripts" / "gen_env_example.py"
ENV_EXAMPLE = REPO / ".env.example"


def _check(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--check", *extra],
        capture_output=True,
        text=True,
        check=False,
    )


def test_committed_env_example_has_no_drift() -> None:
    result = _check()
    assert result.returncode == 0, result.stderr


def test_every_bootstrap_variable_is_documented_with_its_default() -> None:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assignments = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in lines
        if line and not line.startswith("#") and "=" in line
    }
    examples = [var for var in BOOTSTRAP_ENV if var.in_example]
    assert set(assignments) == {var.name for var in examples}
    for var in examples:
        assert assignments[var.name] == (var.default or ""), var.name
        assert any(line.startswith(f"# {var.description}") for line in lines), var.name


def test_credentials_are_empty_placeholders() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "\nLLM_API_KEY=\n" in text
    assert "\nVCS_TOKEN=\n" in text


def test_drift_is_detected(tmp_path: Path) -> None:
    stale = tmp_path / ".env.example"
    stale.write_text("# old\nAGENT_NAME=michael\n", encoding="utf-8")
    result = _check("--path", str(stale))
    assert result.returncode == 1
    assert "out of date" in result.stderr


def test_missing_file_is_drift(tmp_path: Path) -> None:
    result = _check("--path", str(tmp_path / "absent.env"))
    assert result.returncode == 1
