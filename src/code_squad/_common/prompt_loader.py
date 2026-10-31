from __future__ import annotations

import importlib.resources
import os
from pathlib import Path

_OVERRIDE_ENV = "AGENT_PROMPT_FILE"


def load_prompt(agent_name: str) -> str:
    if not agent_name.isidentifier():
        raise ValueError(f"invalid agent name: {agent_name!r}")
    override = os.environ.get(_OVERRIDE_ENV)
    if override:
        return Path(override).read_text(encoding="utf-8")
    resource = importlib.resources.files(f"code_squad.{agent_name}").joinpath(
        "prompt.md"
    )
    return resource.read_text(encoding="utf-8")
