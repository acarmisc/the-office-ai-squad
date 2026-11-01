"""Generate the committed JSON Schemas from the pydantic models.

``--check`` writes nothing and exits 1 when a committed schema has drifted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from code_squad._common.config.schema import (
    Baseline,
    ProjectsFile,
    RepoConfig,
)
from code_squad._common.contract import Finding, InvocationRequest

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
SCHEMA_DIR: Final[Path] = ROOT / "schemas"
TARGETS: Final[dict[str, type[BaseModel]]] = {
    "squad-config.schema.json": RepoConfig,
    "projects.schema.json": ProjectsFile,
    "invocation.schema.json": InvocationRequest,
    "finding.schema.json": Finding,
    "baseline.schema.json": Baseline,
}


def render(model: type[BaseModel]) -> str:
    schema = model.model_json_schema(mode="validation")
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def render_all() -> dict[Path, str]:
    return {SCHEMA_DIR / name: render(model) for name, model in TARGETS.items()}


def main(argv: list[str]) -> int:
    check = "--check" in argv
    drift: list[str] = []
    for path, text in render_all().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        if check:
            drift.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    if drift:
        for name in drift:
            print(f"schema drift: {name} (run: just docs-gen)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
