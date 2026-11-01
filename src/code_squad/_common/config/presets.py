"""Tool presets for extra agents. Only ``publish_review`` may write externally."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from code_squad._common.config.errors import ConfigError

REVIEW_READONLY_TOOLS: Final[tuple[str, ...]] = (
    "get_review_context",
    "read_file",
    "search_repo",
    "list_tree",
    "load_skill",
    "read_knowledge",
    "finish",
)
REVIEW_PUBLISH_TOOLS: Final[tuple[str, ...]] = (
    *REVIEW_READONLY_TOOLS,
    "publish_review",
)
TOOL_PRESETS: Final[Mapping[str, tuple[str, ...]]] = {
    "review_readonly": REVIEW_READONLY_TOOLS,
    "review_publish": REVIEW_PUBLISH_TOOLS,
}


def preset_tools(name: str) -> tuple[str, ...]:
    try:
        return TOOL_PRESETS[name]
    except KeyError as exc:
        raise ConfigError(f"unknown tool preset {name!r}") from exc
