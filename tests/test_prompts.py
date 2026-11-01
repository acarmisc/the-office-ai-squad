from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from code_squad._common.registry import AGENT_IDS

_REPO = Path(__file__).resolve().parents[1]


def _load_checker() -> ModuleType:
    path = _REPO / "scripts" / "check_prompts.py"
    spec = importlib.util.spec_from_file_location("check_prompts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_agent_prompt_passes_the_prompt_checker() -> None:
    checker = _load_checker()
    prompts = sorted((_REPO / "src" / "code_squad").glob("*/prompt.md"))
    assert {p.parent.name for p in prompts} == set(AGENT_IDS)
    for prompt in prompts:
        assert checker.check_prompt(prompt) == [], prompt.name
