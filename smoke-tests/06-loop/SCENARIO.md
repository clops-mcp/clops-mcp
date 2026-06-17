# Scenario 06: loop

## What this tests

`loop` execution. Verifies:

- The loop dispatches its body Op repeatedly.
- After each iteration, the runtime evaluates `until(output)` against the latest output.
- The loop terminates when `until` returns truthy.
- Each iteration is a fresh `OpExecution` in the state graph.
- The loop respects `max_iterations` if the predicate never satisfies.

## Setup

From this folder:

```bash
pip install -e ./library
claude
```

## Prompt

> Start the "Brainstorm" process with input "running daily" and follow the instructions until done.

## Expected behavior

1. Main thread loads the `clops-orchestration` skill.
2. Calls `mcp__clops__start_process(process="Brainstorm", input="running daily")`.
3. MCP returns dispatch for **Seed**. Seed subagent emits a 1-2 item bullet list, calls `complete`.
4. Main thread relays `step_complete`. MCP returns dispatch for **Refine** (loop iteration 1).
5. Refine subagent adds one benefit, returns the updated list, calls `complete`. No `[done]` yet.
6. Main thread relays `step_complete`. MCP evaluates `until` against the output (no `[done]` found → false), returns dispatch for **Refine** again.
7. Iteration repeats. Each iteration adds one benefit. When the list has 5+ benefits, the Refine subagent appends `[done]` to the output.
8. Main thread relays that output. MCP evaluates `until` (`[done]` present → true), terminates the loop, returns `{action: "done", output: <final list>}`.
9. Main thread shows the final list to the user.

## Pass criteria

- **Multiple** Agent dispatches for `Refine` (iteration count varies — anywhere from 3 to 7 is fine depending on how quickly the agent judges the list done).
- Exactly **one** Agent dispatch for `Seed` (the seed runs once at the start).
- Final output contains `[done]` AND has 5 or more distinct benefits.
- No `max_iterations` failure (the predicate satisfied within 8 iterations).
- No `call_tool`, no `need`, no `abort_run`.

## Common failure modes

- **`[done]` never appears — loop hits max_iterations.** The Refine subagent isn't adding the marker. Check the Intent — it's explicit, but the agent may still forget. Re-running usually fixes.
- **`[done]` appears after only 1-2 benefits.** Agent is too eager. Intent says "5 or more" — if it lands early, that's still a pass for the smoke (loop terminates) but worth noting as ambiguity in the Op's Intent.
- **Loop fires way more times than expected.** The `until` predicate isn't seeing the marker. Inspect the dispatch's `step_complete` return value — if the output contains `[done]` but the loop still iterates, the runtime's loop handling is broken.
- **Only Seed dispatched, immediately `done`.** The loop isn't running at all. Check that `body = sequence(Seed, loop(...))` is set on `Brainstorm` and that the runtime handles the `Loop` data structure.
