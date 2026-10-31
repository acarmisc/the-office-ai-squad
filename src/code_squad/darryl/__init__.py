from code_squad._common.common_tools import finish, read_knowledge
from code_squad._common.prompt_loader import load_prompt
from code_squad._common.spec import AgentSpec

SPEC = AgentSpec(
    name="darryl",
    description="Reviews CI/CD, containers, IaC and Kubernetes manifests.",
    role="devops",
    system_prompt=load_prompt("darryl"),
    task_template="Action: {action}. Project: {project}. Target: {target}.",
    tools=(finish, read_knowledge),
    model_id="sonnet-5-5",
    input_key="prompt",
    modes=("review", "troubleshoot"),
)
