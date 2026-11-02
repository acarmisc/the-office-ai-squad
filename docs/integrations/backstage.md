# Backstage

The squad is described in `catalog-info.yaml` at the root of the repository. Each agent is a catalog `Component` with
`spec.type: ai-agent`, so the [AI Agents plugin](https://github.com/acarmisc/backstage-plugin-ai-agents) lists it on the
`/ai-agents` page, probes its health and shows its activity. Each agent also has an `API` entity with its OpenAPI contract.

## Register the squad in Backstage

1. Make sure the owner exists. `catalog-info.yaml` uses `group:default/platform-team` for every entity and the System points to
   the domain `developer-tools`. Replace both with a group and a domain that exist in your catalog, otherwise the relations stay
   unresolved.
2. Add the file as a catalog location in the `app-config.yaml` of Backstage, or register it from the UI
   (**Catalog → Create → Register existing component**):

   ```yaml
   catalog:
     locations:
       - type: url
         target: https://github.com/acarmisc/the-office-ai-squad/blob/main/catalog-info.yaml
         rules:
           - allow: [System, Component, API]
   ```

   Backstage reads the file through its GitHub integration (`integrations.github`). For a private fork, give that integration a
   token that can read the repository.
3. Wait for the next catalog refresh or refresh the entities from their page. You should see one System, six Components
   (`code-squad-michael`, `-jim`, `-angela`, `-dwight`, `-darryl`, `-pam`) and six APIs.

## Show the agents on the AI Agents page

The AI Agents plugin needs the frontend and backend packages installed in Backstage (see its README). Then:

```yaml
# app-config.yaml of Backstage
ai-agents:
  probeAllowlist:
    - http://code-squad-*.code-squad.svc.cluster.local:8080
```

Status probing is deny-by-default. Without that line the cards list the agents but their status stays `unknown`. If Backstage
runs outside the cluster, expose the agents through an ingress and allow that origin instead, and change the `endpoint` and
`health` annotations accordingly.

The in-cluster host names in the annotations assume the namespace `code-squad`. If you install the chart elsewhere, change the
`ai-agent.io/endpoint` and `ai-agent.io/health` annotations of each Component.

## Annotations used

| Annotation | Value |
| --- | --- |
| `ai-agent.io/runtime` | `http`: a container that serves `POST /invocations` and `GET /ping` |
| `ai-agent.io/runtime-handle` | The Kubernetes Service name, `code-squad-<agent>` |
| `ai-agent.io/endpoint`, `ai-agent.io/health` | Service base URL, and the same URL plus `/ping` |
| `ai-agent.io/telemetry-id` | `code-squad-<agent>`, equal to the OpenTelemetry service name |
| `ai-agent.io/squad` | `code-squad` |
| `ai-agent.io/capabilities` | Chips shown on the card, as `label:category` |
| `ai-agent.io/hire-schema`, `ai-agent.io/prompt-template` | The form of the Hire dialog and its prompt |
| `ai-agent.io/billing-model` | `per-token` (spend is read from LiteLLM) |

`tests/test_catalog.py` checks these rules: the plugin's entity type, valid capability categories, a Hire form that is valid JSON,
and a prompt template whose placeholders all exist in the form.

## Running an agent from the Hire dialog

The plugin has invoker modules for AWS Bedrock AgentCore and kagent only. Runtime `http` needs a small backend module in the
plugin repository that registers an invoker for `http` and posts the plugin payload to `<endpoint>/invocations`. Until it
exists, the dialog shows a copyable request instead of running the agent.

The plugin always sends `post` (false for a dry run, true only from **Confirm and publish**), together with `prompt`, `target`,
`project`, `mode`, `model`, `knowledge_base_ids`, `litellm_tags` and `trace_user_id`.

### Gaps to close before the module works end to end

- The request model rejects unknown fields (`extra="forbid"`) and does not define `trace_user_id` or `knowledge_base_ids`, so a
  plugin request is answered with `422`. Both must be accepted (the second can be ignored).
- The result has no `result` field. The plugin looks for `result`, `response`, `output`, `text` or `completion`; otherwise it
  shows the whole JSON. Adding a markdown `result` string gives a readable answer in the dialog.
- For the Activity view, the Langfuse module expects an agent span named `code-squad-<agent>-invoke` and tool spans with
  `gen_ai.tool.name`. The service name already matches (`code-squad-<agent>`); check the span names in a trace.

## Activity and spend

Activity is read from Langfuse with the plugin's Langfuse module (`ai-agents.telemetry.langfuse`). Leave `servicePrefix` empty:
`ai-agent.io/telemetry-id` already equals the service name. Spend comes from LiteLLM through the tags
`session:<thread>`, `backstage-entity:<ref>` and `invoked-by:<user>` that the plugin adds; the squad passes `litellm_tags`
through to the gateway.

## Changing the catalog

Edit `catalog-info.yaml` by hand and run `uv run pytest tests/test_catalog.py`. A new agent needs one Component (type
`ai-agent`) and one API, as described in the [contributing guide](../contributing/index.md).
