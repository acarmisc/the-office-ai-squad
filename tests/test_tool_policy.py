from __future__ import annotations

import pytest
from strands import tool

from code_squad._common.common_tools import finish, read_knowledge
from code_squad._common.registry import all_specs
from code_squad._common.tool_policy import (
    TOOL_POLICY,
    ToolClass,
    UnclassifiedToolError,
    classify,
    tool_name,
    unclassified,
)


@tool
def mystery_tool() -> str:
    """A tool nobody classified."""
    return "?"


def test_every_tool_of_every_registered_agent_is_classified() -> None:
    for spec in all_specs():
        assert unclassified(spec.tools) == [], spec.name


def test_no_agent_other_than_pam_has_local_mutation_tools() -> None:
    for spec in all_specs():
        if spec.name == "pam":
            continue
        classes = [classify(tool_name(tool)) for tool in spec.tools]
        assert ToolClass.LOCAL_MUTATION not in classes, spec.name


def test_unclassified_tool_is_detected() -> None:
    assert unclassified([finish, mystery_tool]) == ["mystery_tool"]


def test_classify_unknown_name_raises_keyerror_subclass() -> None:
    with pytest.raises(UnclassifiedToolError):
        classify("no_such_tool")
    assert issubclass(UnclassifiedToolError, KeyError)


def test_publish_review_is_external_write() -> None:
    assert classify("publish_review") is ToolClass.EXTERNAL_WRITE
    assert TOOL_POLICY["publish_review"] is ToolClass.EXTERNAL_WRITE


def test_common_read_tools_are_read_class() -> None:
    assert classify("finish") is ToolClass.READ
    assert classify("read_knowledge") is ToolClass.READ


def test_tool_name_reads_decorated_tool_and_plain_function() -> None:
    assert tool_name(finish) == "finish"
    assert tool_name(read_knowledge) == "read_knowledge"

    def plain_helper() -> None:
        return None

    assert tool_name(plain_helper) == "plain_helper"


def test_tool_name_rejects_unnamed_objects() -> None:
    with pytest.raises(TypeError):
        tool_name(object())
