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
from code_squad.dwight.tools import (
    lookup_cve,
    lookup_vulnerabilities,
    parse_dependencies,
    search_advisories,
)

SPEC = AgentSpec(
    name="dwight",
    description="Assesses the security posture of code, config and dependencies.",
    role="sec-reviewer",
    system_prompt=load_prompt("dwight"),
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
        parse_dependencies,
        lookup_vulnerabilities,
        lookup_cve,
        search_advisories,
        publish_review,
        finish,
    ),
    model_id="sonnet-5-5",
    max_iterations=30,
    input_key="prompt",
    modes=("review",),
)
