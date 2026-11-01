from __future__ import annotations

import pytest

from code_squad._common.config.errors import ConfigError
from code_squad._common.config.presets import (
    REVIEW_PUBLISH_TOOLS,
    REVIEW_READONLY_TOOLS,
    TOOL_PRESETS,
    preset_tools,
)
from code_squad._common.tool_policy import TOOL_POLICY, ToolClass


@pytest.mark.parametrize("preset", sorted(TOOL_PRESETS))
def test_every_preset_tool_is_classified(preset: str) -> None:
    for tool in preset_tools(preset):
        assert tool in TOOL_POLICY, f"{preset} names unclassified tool {tool}"


def test_readonly_preset_has_no_external_write_tools() -> None:
    external = [
        t for t in REVIEW_READONLY_TOOLS if TOOL_POLICY[t] is ToolClass.EXTERNAL_WRITE
    ]
    assert external == []


def test_publish_preset_adds_only_publish_review_as_external_write() -> None:
    external = [
        t for t in REVIEW_PUBLISH_TOOLS if TOOL_POLICY[t] is ToolClass.EXTERNAL_WRITE
    ]
    assert external == ["publish_review"]


def test_presets_have_the_brief_composition() -> None:
    assert set(REVIEW_READONLY_TOOLS) == {
        "get_review_context",
        "read_file",
        "search_repo",
        "list_tree",
        "load_skill",
        "read_knowledge",
        "finish",
    }
    assert set(REVIEW_PUBLISH_TOOLS) == set(REVIEW_READONLY_TOOLS) | {"publish_review"}


def test_unknown_preset_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="unknown tool preset"):
        preset_tools("everything")
