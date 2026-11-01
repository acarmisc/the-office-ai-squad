from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_committed_schemas_match_the_pydantic_models() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_schemas.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_drift_is_detected_without_writing(tmp_path: Path) -> None:
    schema = ROOT / "schemas" / "finding.schema.json"
    original = schema.read_text(encoding="utf-8")
    try:
        schema.write_text(original.replace('"title"', '"title "', 1), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "gen_schemas.py"), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "finding.schema.json" in result.stderr
        assert schema.read_text(encoding="utf-8") != original
    finally:
        schema.write_text(original, encoding="utf-8")
