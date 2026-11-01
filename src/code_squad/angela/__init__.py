from code_squad._common.common_tools import finish, read_knowledge
from code_squad._common.prompt_loader import load_prompt
from code_squad._common.review_tools import (
    get_review_context,
    list_tree,
    publish_review,
    read_file,
    search_repo,
)
from code_squad._common.skills.tools import get_project_skills, load_skill
from code_squad._common.spec import AgentSpec

SPEC = AgentSpec(
    name="angela",
    description="Reviews Java and JVM changes, including Spring applications.",
    role="java-reviewer",
    system_prompt=load_prompt("angela"),
    task_template=(
        "Review change request {target} in project {project}. Action: {action}."
    ),
    tools=(
        get_review_context,
        read_file,
        search_repo,
        list_tree,
        get_project_skills,
        load_skill,
        read_knowledge,
        publish_review,
        finish,
    ),
    model_id="sonnet-5-5",
    max_iterations=25,
    input_key="prompt",
    modes=("review",),
)
