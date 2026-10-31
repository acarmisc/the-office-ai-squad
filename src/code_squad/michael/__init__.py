from code_squad._common.common_tools import finish, read_knowledge
from code_squad._common.prompt_loader import load_prompt
from code_squad._common.spec import AgentSpec

SPEC = AgentSpec(
    name="michael",
    description="Routes requests to specialist agents and consolidates their results.",
    role="orchestrator",
    system_prompt=load_prompt("michael"),
    task_template="Action: {action}. Project: {project}. Target: {target}.",
    tools=(finish, read_knowledge),
    model_id="haiku-5-5",
    input_key="prompt",
    modes=("review", "troubleshoot", "implementer", "question"),
)
