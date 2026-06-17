# Scenario 02: pipeline

## What this tests

`sequence(A, B)` composition. Verifies the runtime walks the body, dispatches each leaf in order, threads each leaf's output as the next leaf's input, and surfaces only the final output to the user.

## Setup

From this folder:

```bash
pip install -e ./library
claude
```

## Prompt

> Start the "LoudIfy" process with input "hello world" and follow the instructions until done.

## Expected behavior

1. Main thread loads the `clops-orchestration` skill.
2. Calls `mcp__clops__start_process(process="LoudIfy", input="hello world")`.
   - MCP returns `action: "dispatch"` for the **first leaf** — `Capitalize`. The `agent_config.description` should start with "Execute Capitalize".
3. Dispatches Agent (clops-executor); subagent calls `complete` with output like `"HELLO WORLD"`.
4. Main thread relays via `mcp__clops__step_complete(run_id, "HELLO WORLD")`.
   - MCP returns a **new dispatch instruction** for the second leaf — `Exclaim`. Its prompt's `## Your input` section contains `HELLO WORLD`.
5. Dispatches Agent again; second subagent calls `complete` with output like `"HELLO WORLD!!!"`.
6. Main thread relays via `mcp__clops__step_complete(run_id, "HELLO WORLD!!!")`.
7. MCP returns `{action: "done", output: "HELLO WORLD!!!"}`.
8. Main thread reports the final output.

## Pass criteria

- Exactly **two** Agent dispatches, in order: Capitalize, then Exclaim.
- Exactly **two** `mcp__clops__step_complete` calls.
- The second leaf's prompt visibly receives the first leaf's output as its `Your input`. (You can check this by looking at the dispatch instruction the MCP returns after the first `step_complete`.)
- Final output to the user is the input phrase, uppercased, with three trailing `!`s. Minor variation OK as long as: it's uppercase and ends with `!!!`.
- No `mcp__clops__call_tool`, no `need`, no `abort_run`.

## Common failure modes

- **Both leaves dispatched at once.** Wrong — Phase 1b is sequential. If you see two Agent invocations before the first one returns, the relay loop is broken.
- **Only one dispatch.** The composition didn't advance — likely the runtime treated `LoudIfy` as a leaf instead of walking its `body`. Check that `body = sequence(Capitalize, Exclaim)` is set on the `LoudIfy` class.
- **Final output is missing the exclamation marks.** The second leaf wasn't dispatched, or its output didn't reach `step_complete`.
- **Final output is the input verbatim ("hello world").** The first leaf's output didn't thread through. Check the Capitalize subagent actually capitalized.
