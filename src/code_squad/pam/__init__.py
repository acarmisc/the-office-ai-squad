from code_squad._common.common_tools import finish, read_knowledge
from code_squad._common.prompt_loader import load_prompt
from code_squad._common.review_tools import list_tree, read_file, search_repo
from code_squad._common.skills.tools import get_project_skills, load_skill
from code_squad._common.spec import AgentSpec
from code_squad.pam.tools import (
    apply_patch,
    commit,
    get_task,
    open_change_request,
    push_branch,
    run_checks,
    run_command,
    sandbox_diff,
    sandbox_list,
    sandbox_read,
    start_work,
    write_file,
)

SPEC = AgentSpec(
    name="pam",
    description="Senior React engineer: plans frontend work and implements tasks.",
    role="frontend-dev",
    system_prompt=load_prompt("pam"),
    task_template="Mode: {action}. Project: {project}. Task: {target}.",
    tools=(
        read_file,
        search_repo,
        list_tree,
        get_task,
        get_project_skills,
        load_skill,
        read_knowledge,
        sandbox_read,
        sandbox_list,
        sandbox_diff,
        start_work,
        write_file,
        apply_patch,
        run_command,
        run_checks,
        commit,
        push_branch,
        open_change_request,
        finish,
    ),
    model_id="sonnet-5-5",
    max_tokens=16384,
    max_iterations=60,
    accepts_attachments=True,
    input_key="prompt",
    modes=("advisor", "implementer"),
)
