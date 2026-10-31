from code_squad._common.common_tools import finish, read_knowledge
from code_squad._common.prompt_loader import load_prompt
from code_squad._common.spec import AgentSpec

SPEC = AgentSpec(
    name="angela",
    description="Reviews Java and JVM changes, including Spring applications.",
    role="java-reviewer",
    system_prompt=load_prompt("angela"),
    task_template="Action: {action}. Project: {project}. Target: {target}.",
    tools=(finish, read_knowledge),
    model_id="sonnet-5-5",
    input_key="prompt",
    modes=("review",),
)
