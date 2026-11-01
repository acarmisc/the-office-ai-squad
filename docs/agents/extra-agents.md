# Extra agents

An extra agent is a specialist declared in configuration, without code. A Python reviewer, a Go
reviewer or a Terraform reviewer can use the same runtime, the same finding pipeline and the same
publication path as the built-in agents. The example in `examples/org/extra-agents.yaml` defines a
Python reviewer named `oscar`.

An extra agent has a prompt, optional knowledge directories, a tool preset and a model. It runs in review
mode. `michael` routes changes to it by glob, and it returns findings to `michael` like any specialist.

## Declaring one

The declaration belongs to the organisation file. A repository cannot add an extra agent; the field is
organisation-only.

```yaml
extra_agents:
  - id: oscar
    description: Python reviewer for correctness, typing and security hygiene.
    prompt_path: /etc/squad/agents/oscar/prompt.md
    knowledge_dirs:
      - /etc/squad/agents/oscar/knowledge
    tool_preset: review_publish
    model: sonnet-5-5
    routes:
      - "**/*.py"
```

| Field | Rule |
| --- | --- |
| `id` | Lowercase, starts with a letter, 2 to 31 characters (`^[a-z][a-z0-9]{1,30}$`). It must not be a built-in id, and must be unique. |
| `description` | One line, up to 200 characters. Used in the registry and in the catalogue. |
| `prompt_path` | Absolute or relative path to a markdown prompt. It must be readable and not empty when the process starts. |
| `knowledge_dirs` | Directories whose `.md` files `read_knowledge` can return. They are searched after the agent's own pack and the shared pack. |
| `tool_preset` | `review_readonly` or `review_publish`. See below. |
| `model` | Model alias. Defaults to `sonnet-5-5`. |
| `routes` | Changed-file globs that send a change to this agent. |

Tool presets:

| Preset | Tools |
| --- | --- |
| `review_readonly` | `get_review_context`, `read_file`, `search_repo`, `list_tree`, `load_skill`, `read_knowledge`, `finish` |
| `review_publish` | The read-only set plus `publish_review` (external write, gated by posting) |

No preset contains a mutating tool. The tests in `tests/config/test_presets.py` check that every preset tool is
classified, and the tool policy allows only `publish_review` as an external write.

## Running it

Registration happens at process start: the server reads the organisation file and registers each extra
agent before it builds the HTTP app. An extra agent is served by a process whose `AGENT_NAME` equals its
id, from the same image. `michael` calls it at `routing.specialist_urls[<id>]`, `ORCHESTRATOR_SPECIALIST_URLS`,
or the default service name `http://code-squad-<id>.<namespace>.svc:8080`.

<!-- TODO(architect): the Helm chart renders only the six built-in agents and has no value for extra
agents. An operator must add a Deployment, a Service named code-squad-<id>, a ServiceAccount, and mounts for
the prompt and knowledge directories. Decide whether the chart should support extra agents. -->

The extra agent's `prompt.md` is a normal system prompt. The runtime appends the untrusted-content rule, the
dry-run note and the skill index, as for the built-in agents. Write the prompt in the same shape as the
built-in prompts: role and boundaries, untrusted content, method, severity rubric, what not to flag, output
contract (which must end with `finish`), and limits.

## Behaviour and limits

- Routing works as for built-in agents. The change's risk tier and the verdict rules of `michael` apply to
  the extra agent's findings in the same way.
- Its findings use the same schema and the same deterministic anchoring, deduplication and verdict pipeline.
- Its knowledge is limited to the directories listed. `read_knowledge` never leaves them, and a symlink that
  escapes a directory is refused.
- Its budgets and per-agent settings come from `agents.<id>` like any agent. Only the settings that are
  enforced for built-in agents are enforced here.
- Its tool set cannot grow through configuration. The `tool_allowlist` can only narrow it.

## Testing an extra agent

1. Validate the file: `squad config validate squad.yaml` checks the schema, the id rules and the preset name.
2. Start the agent locally with `AGENT_NAME=oscar`, the organisation file set in `SQUAD_CONFIG_FILE`, and
   `GET /ready`. A missing prompt file makes `/ready` return `503`.
3. Send a dry-run invocation with `mode: "review"`, a `project` and a `target`. Check `warnings` for
   unknown topics or skipped skills.
4. Run the squad's own tests for the registration and preset rules: `just test tests/test_registry.py tests/config`.

## Known limitations

- No chart support yet (see the TODO above).
- The generated agent defaults page (`reference/agents.md`) covers the built-in agents only.
- The eval harness has golden cases for built-in reviewers only.
