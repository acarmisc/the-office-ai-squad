from code_squad._common.common_tools import finish, read_knowledge
from code_squad._common.prompt_loader import load_prompt
from code_squad._common.review_tools import (
    get_review_context,
    list_tree,
    read_file,
    search_repo,
)
from code_squad._common.skills.tools import get_project_skills, load_skill
from code_squad._common.spec import AgentSpec
from code_squad.darryl.tools import TROUBLESHOOT_TOOLS, publish_review

SPEC = AgentSpec(
    name="darryl",
    description=(
        "Reviews CI/CD, containers, IaC and Kubernetes manifests, and troubleshoots "
        "production issues with read-only access."
    ),
    role="devops",
    system_prompt=load_prompt("darryl"),
    task_template="Mode: {action}. Project: {project}. Target: {target}.",
    tools=(
        finish,
        read_knowledge,
        get_review_context,
        read_file,
        search_repo,
        list_tree,
        get_project_skills,
        load_skill,
        publish_review,
        *TROUBLESHOOT_TOOLS,
    ),
    model_id="sonnet-5-5",
    max_iterations=30,
    input_key="prompt",
    modes=("review", "troubleshoot"),
)
