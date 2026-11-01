from __future__ import annotations

import pytest

from code_squad._common.tool_policy import ToolClass, classify, tool_name
from code_squad.dwight import tools

DWIGHT_READ_TOOLS = (
    "parse_dependencies",
    "lookup_vulnerabilities",
    "lookup_cve",
    "search_advisories",
)


@pytest.mark.parametrize("name", DWIGHT_READ_TOOLS)
def test_dwight_intel_tools_are_read_class(name: str) -> None:
    assert classify(name) is ToolClass.READ


def test_dwight_tool_objects_carry_the_classified_names() -> None:
    names = {
        tool_name(tools.parse_dependencies),
        tool_name(tools.lookup_vulnerabilities),
        tool_name(tools.lookup_cve),
        tool_name(tools.search_advisories),
    }
    assert names == set(DWIGHT_READ_TOOLS)
