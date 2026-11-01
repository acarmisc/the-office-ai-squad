# Knowledge packs

A knowledge pack is a set of reference guidelines that an agent reads with the `read_knowledge` tool. Packs
hold the expertise that does not change with each project: how a hook should be written, what a Kubernetes
readiness probe failure looks like, which Spring transaction pitfalls matter. Project conventions belong in
[skills](skills-authoring.md), not in packs.

The prompt of each agent lists the topics it uses, and it keeps the list short so the context stays lean. The
pack holds the detail.

## Layout

A pack is a directory of markdown files. Each file is a topic. The topic name is its path without `.md`.

```text
src/code_squad/angela/knowledge/
  README.md                 # describes the pack; not a topic
  java/
    index.md                # topic java/index: the rule prefixes and the list of topics
    spring-core.md          # topic java/spring-core
    jpa-persistence.md      # topic java/jpa-persistence
```

Rules for topic names: each path segment uses lower-case letters, digits and dashes, and the names are
checked by the tool. A file named `README.md` is documentation and is never returned as a topic.

## Where agents look

`read_knowledge(topic)` searches three roots, in this order, and returns the first match:

| Order | Root | Who sees it |
| --- | --- | --- |
| 1 | The agent's own pack, `code_squad/<agent>/knowledge/` | That agent. |
| 2 | The shared pack, `code_squad/_common/knowledge/` | Every agent. It holds the React topics (`react/*`). |
| 3 | `knowledge_extra_dirs`: absolute directories from configuration (organisation only) and from `extra_agents[].knowledge_dirs` | The agent they are configured for. |

A topic that is not found returns the list of available topics, which is how an agent discovers a topic it
did not know. A resolved path must stay inside its root, so a symlink cannot read files outside a pack.

## Index topics

Each pack should have an index topic (for example `java/index`). It lists the topics, the rule-id prefixes the
pack uses, and when to read each topic. The reviewers read the index first when they are unsure which topic
applies. Dwight's index also states the id families (`SEC-INJECT-`, `SEC-DEP-`), so the model can cite a stable
rule id.

## Writing a topic

- **Start with the rule, then the evidence.** One rule per heading, a one-line statement, then the code pattern
  that breaks it and the pattern that fixes it.
- **Say what a reviewer should cite.** A reviewer produces findings with evidence; give it the evidence
  to point at (a concrete construct, not a general principle).
- **Name the version.** Each topic says which framework or language version it was written for. The React pack
  marks version-specific APIs, and the prompt forbids suggesting APIs newer than the project uses.
- **Keep it short.** A topic is a few hundred to a few thousand words. Move long reference material to a separate
  topic.
- **Avoid noise.** List what is not a finding (style that a linter enforces, speculation without evidence).
- **No secrets, real hostnames or tokens** in examples. Use obvious placeholders.

## Adding a topic to an existing pack

1. Create the markdown file in the pack directory (for example `src/code_squad/jim/knowledge/react/…`
   for a React-only topic, or the shared pack for a topic every agent should see).
2. Add the topic to the pack's index, with the rule prefix it uses.
3. If the prompt should use it, add it to the agent's prompt index. Keep the prompt lean: one line per topic.
4. Check the topic name: `read_knowledge` refuses names that do not match the segment rules.
5. Add a case to the eval set if the topic changes review behaviour (see [Testing](../testing/index.md)).

## Adding a pack for a new agent

A new agent (see [Extra agents](../agents/extra-agents.md)) does not need code in the platform. Create the
directory, write an index topic and point `knowledge_dirs` at it. The directory must be readable by the
agent's process. In a container, mount it read-only.

## Organisation-level knowledge

Teams sometimes want their own guidance available to every project without putting it in each repository.
Use `knowledge_extra_dirs` in the organisation file for an agent, mounted from a ConfigMap or a volume. The
setting is organisation-only, and the directory is searched after the built-in packs. Put only guidance here
that is safe to be read by any review: the model reads it as trusted guidance, while repository content stays
untrusted.

## Limits and maintenance

- Packs are loaded when the agent reads them. Changes to files in the image require a rebuild; changes to mounted
  directories take effect on the next read.
- The packs have no run-time version check. Keep the version note in each topic accurate when you edit it.
- Packs are reviewed like code. A knowledge change that alters review behaviour needs an eval case.
