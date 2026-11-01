# Your first change

This walkthrough makes a small, real change, adds its test and gets it through the gate. Two examples follow: a knowledge-pack rule
(the simplest change, no code) and a read-only tool (the change most contributors need). Both end with `just check`.

## Before you start

```bash
git clone https://github.com/acarmisc/the-office-ai-squad.git
cd the-office-ai-squad
uv sync
just check
```

`just check` runs the whole gate. It must be green before you change anything, so a failure after your change is yours. Each step is
described in [Testing](../testing/index.md). If you do not have `helm` or `kubeconform`, the chart step fails; run the other steps with
`just lint typecheck test prompts docs-check docs secret-scan` and ask a maintainer to run `just helm-lint`.

## Example 1: add a rule to a knowledge pack

Use this when a reviewer should know a guideline it does not know. The rule lives in a topic file, not in code.

1. **Find the topic.** Read the index of the pack, for example `src/code_squad/angela/knowledge/java/index.md`. Each index lists the rule
   prefixes and the topics. Pick the topic that fits, or create one, following [knowledge packs](../onboarding/knowledge-packs.md).
2. **Write the rule** in the topic file. Give it a stable id (the prefix in the index), the trigger, the bad pattern and the fix. Keep
   the text short: the agent reads it on every run.
3. **Link it from the index** so the agent discovers the topic.
4. **Test it.** The rule is reachable through `read_knowledge`. Add a test next to the existing knowledge tests, using the same fixtures;
   check that `read_knowledge("<topic>")` returns your rule and that an unknown topic returns the topic list. The existing tests in
   `tests/test_common_tools.py` show the pattern.
5. **Check the prompt budget.** If you named the topic in the prompt, run `just prompts`.
6. **If the rule changes review behaviour** (it will produce findings that were not produced before), add a golden case, as described in
   [Testing](../testing/index.md#adding-a-golden-case).

```bash
uv run pytest tests/test_common_tools.py -q
just prompts
just check
```

## Example 2: add a read-only tool

Use this when an agent needs information it cannot get today. This example adds a `READ` tool. A tool that writes outside the sandbox
is a different change and needs an ADR first; see [contributing](index.md#adding-a-tool-and-classifying-it).

1. **Write the tool** as a Strands tool with an explicit signature and a docstring. The docstring is the model's instruction. Put it in
   the agent's package (for example `src/code_squad/jim/tools.py`) or in `_common/common_tools.py` if every agent may use it.

   ```python
   from strands import tool


   @tool
   def count_lines(path: str) -> str:
       """Count the lines of a file in the change, for sizing a finding.

       Args:
           path: Repository path of a file that the change touches.
       """
       ...
   ```

   Read a value through `code_squad._common.context.current()`, never through a global. Return a short string.

2. **Classify it** in `src/code_squad/_common/tool_policy.py`:

   ```python
   TOOL_POLICY: dict[str, ToolClass] = {
       ...
       "count_lines": ToolClass.READ,
   }
   ```

   An unclassified name is refused when the model calls it.

3. **Add it to the agent's `SPEC.tools` only** (`src/code_squad/jim/__init__.py`). Do not add it to a shared preset.

4. **Test the classification and the behaviour.** Add a test that asserts the policy class, and a scripted run in which the model calls
   the tool and the result is recorded. Use `ScriptedModel` and `ToolCall`, as in `tests/agents/test_jim.py`:

   ```python
   from code_squad._common.fake_model import ScriptedModel, ToolCall, Turn

   turns = [
       Turn((ToolCall("count_lines", {"path": "src/a.tsx"}),)),
       Turn(
           (ToolCall("finish", {"verdict": "approve", "summary": "ok", "findings": []}),)
       ),
   ]
   model = ScriptedModel(turns)
   ```

   Assert on the run's result and on the tool's effect, not only on the return value.

5. **Regenerate the reference pages.** The tool table in `docs/reference/tool-policy.md` is generated:

   ```bash
   just docs-gen
   git diff --stat docs/reference
   ```

6. **Run the gate.**

   ```bash
   uv run pytest tests/test_tool_policy.py tests/agents/test_jim.py -q
   just check
   ```

## Example 3: fix a bug with a regression test

Every bug fix needs a test that fails before the fix and passes after it. Write the test first, run it, watch it fail for the reason in
the bug report, then change the code. Security-relevant fixes (tool policy, dry run, untrusted content, input validation) must test the
refusal, not only the success path.

## Commit and open the pull request

1. Keep one logical change per commit. Use a conventional message in the imperative mood, for example
   `feat(jim): add count_lines read tool`.
2. Add a line to `CHANGELOG.md` under `## Unreleased` for user-visible changes or configuration defaults.
3. Open the pull request. The template in `.github/pull_request_template.md` lists the checks. Link the issue, and the ADR when the
   change makes a non-trivial choice.
4. CI runs the same gate as `just check`. A red gate is not reviewed.

Read [CONTRIBUTING](https://github.com/acarmisc/the-office-ai-squad/blob/main/CONTRIBUTING.md) for the short version of these rules.
