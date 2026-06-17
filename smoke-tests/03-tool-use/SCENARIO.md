# Scenario 03: tool-use

## What this tests

Op-declared `Tool` invocation through the single `mcp__clops__call_tool` entry point. Verifies:

- The Op's `Tools = [lookup_age]` declaration leads to the tool being mentioned in the dispatched prompt under "Tools available to you."
- The subagent invokes `mcp__clops__call_tool(execution_id, name="lookup_age", arguments={"name": …})` rather than trying to call any per-tool MCP entry (none exists).
- The MCP routes the call to the Python handler and returns its result.
- The subagent uses the result to produce its `complete` output.

## Setup

From this folder:

```bash
pip install -e ./library
claude
```

## Prompt

> Start the "LookupReport" process with input "alice" and follow the instructions until done.

## Expected behavior

1. Main thread loads the `clops-orchestration` skill.
2. Calls `mcp__clops__start_process(process="LookupReport", input="alice")`.
3. MCP returns dispatch instruction. The `agent_config.prompt` includes a "Tools available to you" section listing `lookup_age` and instructing the subagent to invoke it via `mcp__clops__call_tool`.
4. Main thread invokes Agent (clops-executor).
5. Subagent calls `mcp__clops__call_tool(execution_id=…, name="lookup_age", arguments={"name": "alice"})`. The MCP returns `{"name": "alice", "age": 30}`.
6. Subagent calls `mcp__clops__complete(execution_id=…, output="Alice is 30 years old.")` (or close — minor wording variation OK as long as 30 appears).
7. Main thread relays via `mcp__clops__step_complete(run_id, …)`.
8. MCP returns `{action: "done", output: "Alice is 30 years old."}`.
9. Main thread reports the result.

## Pass criteria

- One `mcp__clops__call_tool` call from the subagent with `name="lookup_age"` and the correct argument.
- The tool result (containing `30` for alice) appears in the subagent's `complete` output.
- Final output to the user contains `30` (the age).
- **No per-tool MCP entry was used** — the subagent did NOT call something like `mcp__clops__lookup_age` directly. (If it tried, the MCP would error, but the prompt should make this clear.)
- One Agent dispatch only.

## Common failure modes

- **Subagent calls `mcp__clops__lookup_age` directly.** Symptom of the prompt not making `call_tool` clear, or of the agent ignoring the prompt's instructions. Should fail at the MCP boundary (no such tool).
- **Subagent skips the tool and guesses an age.** Acceptable variation IF the output is plainly a guess and not the deterministic value. Worth flagging — the Op's intent says to USE the tool.
- **`call_tool` returns a structured error.** Most likely cause: subagent passed `arguments` in the wrong shape. Compare against the prompt's parameter description.
- **Tool returns `age: None` for the name.** Only "alice", "bob", and "carol" are in the directory. Try one of those.
