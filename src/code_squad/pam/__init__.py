from code_squad._common.common_tools import finish, read_knowledge
from code_squad._common.prompt_loader import load_prompt
from code_squad._common.spec import AgentSpec

SPEC = AgentSpec(
    name="pam",
    description="Senior React engineer: plans frontend work in advisor mode.",
    role="frontend-dev",
    system_prompt=load_prompt("pam"),
    task_template="Action: {action}. Project: {project}. Target: {target}.",
    tools=(finish, read_knowledge),
    model_id="sonnet-5-5",
    input_key="prompt",
    modes=("advisor", "implementer"),
)
