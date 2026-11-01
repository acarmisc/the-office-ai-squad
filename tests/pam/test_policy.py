from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

from code_squad._common.tool_policy import ToolClass, classify, tool_name
from code_squad.pam import SPEC

SHARED_KNOWLEDGE_ROOT = Path(
    str(resources.files("code_squad._common").joinpath("knowledge"))
)

EXPECTED_CLASSES: dict[str, ToolClass] = {
    "get_task": ToolClass.READ,
    "read_file": ToolClass.READ,
    "search_repo": ToolClass.READ,
    "list_tree": ToolClass.READ,
    "get_project_skills": ToolClass.READ,
    "load_skill": ToolClass.READ,
    "read_knowledge": ToolClass.READ,
    "sandbox_read": ToolClass.READ,
    "sandbox_list": ToolClass.READ,
    "sandbox_diff": ToolClass.READ,
    "finish": ToolClass.READ,
    "start_work": ToolClass.LOCAL_MUTATION,
    "write_file": ToolClass.LOCAL_MUTATION,
    "apply_patch": ToolClass.LOCAL_MUTATION,
    "run_command": ToolClass.LOCAL_MUTATION,
    "run_checks": ToolClass.LOCAL_MUTATION,
    "commit": ToolClass.LOCAL_MUTATION,
    "push_branch": ToolClass.EXTERNAL_WRITE,
    "open_change_request": ToolClass.EXTERNAL_WRITE,
}
FORBIDDEN_WORDS = re.compile(r"approv|confirm|merge|force|delete_branch")


def _names() -> list[str]:
    return [tool_name(item) for item in SPEC.tools]


def test_every_pam_tool_has_the_documented_class() -> None:
    assert set(_names()) == set(EXPECTED_CLASSES)
    for name in _names():
        assert classify(name) is EXPECTED_CLASSES[name], name


def test_only_the_implementer_tools_mutate_locally() -> None:
    mutating = {name for name in _names() if classify(name) is ToolClass.LOCAL_MUTATION}
    assert mutating == {
        "start_work",
        "write_file",
        "apply_patch",
        "run_command",
        "run_checks",
        "commit",
    }


def test_external_writes_are_exactly_push_and_change_request() -> None:
    external = {name for name in _names() if classify(name) is ToolClass.EXTERNAL_WRITE}
    assert external == {"push_branch", "open_change_request"}


def test_there_is_no_approval_confirmation_merge_or_force_tool() -> None:
    for name in _names():
        assert FORBIDDEN_WORDS.search(name) is None, name


def test_spec_declares_both_modes_and_the_agreed_limits() -> None:
    assert SPEC.modes == ("advisor", "implementer")
    assert SPEC.model_id == "sonnet-5-5"
    assert SPEC.max_iterations == 60
    assert SPEC.accepts_attachments is True


def test_task_template_renders_mode_project_and_task() -> None:
    text = SPEC.render_task("#7", "implementer", "acme/web")
    assert text == "Mode: implementer. Project: acme/web. Task: #7."


def test_prompt_names_every_shared_react_topic_it_indexes() -> None:
    topics = set(re.findall(r"`(react/[a-z-]+)`", SPEC.system_prompt))
    assert len(topics) == 15  # the 14 topics plus react/index
    for topic in topics:
        assert (SHARED_KNOWLEDGE_ROOT / f"{topic}.md").is_file()


def test_prompt_states_the_mode_and_approval_rules() -> None:
    prompt = SPEC.system_prompt
    assert "advisor" in prompt and "implementer" in prompt
    assert "no human approval step" in prompt
    assert "Never merge" in prompt
    assert "Never use `approve`" in prompt
