# Scenario 07: gather

## What this tests

`gather` parallel execution. Verifies:

- The runtime returns a `dispatch_parallel` action with N `agent_configs` and N `execution_ids`.
- Main thread issues N Agent tool calls in parallel (emitted in a single message) — not serialized.
- All N subagents call `complete` with their own `execution_id`.
- Main thread relays all N results via `step_complete_parallel`.
- `Synthesize` receives the list of outputs in declaration order.

## Setup

From this folder:

```bash
pip install -e ./library
claude
```

## Prompt

> Start the "ResearchBrief" process with input "remote-first software teams" and follow the instructions until done.

## Expected behavior

1. Main thread loads the `clops-orchestration` skill.
2. Calls `mcp__clops__start_process(process="ResearchBrief", input="remote-first software teams")`.
3. MCP returns dispatch for **Setup**. Setup subagent restates the topic, calls `complete`.
4. Main relays `step_complete`. MCP returns a payload with **`action: "dispatch_parallel"`**:
   - `agent_configs` has three entries (EconomicAngle, SocialAngle, TechnicalAngle).
   - `execution_ids` has three entries matching.
5. Main thread invokes the Agent tool **three times in parallel** — all three Agent tool calls emitted in a single assistant message so Claude Code runs them concurrently.
6. Each of the three subagents reads its prompt, writes one paragraph from its assigned angle, calls `mcp__clops__complete(execution_id=…, output=<paragraph>)`.
7. Once all three subagents have returned, main calls `mcp__clops__step_complete_parallel(run_id, results)` where `results` is a dict mapping each execution_id to its subagent's final text.
8. MCP returns dispatch for **Synthesize**. Synthesize's prompt's "Your input" section contains all three paragraphs (in declaration order: economic, social, technical).
9. Synthesize subagent produces a 3-5 sentence brief, calls `complete`.
10. Main relays `step_complete`. MCP returns `{action: "done", output: <brief>}`.
11. Main reports the brief to the user.

## Pass criteria

- Exactly **one** Agent call for Setup.
- Exactly **three** Agent calls for the angle Ops — issued in parallel in a single assistant message (observable in the Claude Code session transcript).
- Exactly **one** Agent call for Synthesize.
- **Five** `OpExecution` records in the run (Setup, EconomicAngle, SocialAngle, TechnicalAngle, Synthesize).
- Final brief cites all three angles (economic, social, technical).
- Main thread called `mcp__clops__step_complete_parallel` exactly once, with all three execution_ids keyed in `results`.
- No `max_iterations` or `need` errors.

## Common failure modes

- **Main thread serializes the three Agent calls** (one message → one Agent call → wait → next message → next Agent call). Gather semantically works but loses parallelism. Flag this — the skill's rule is explicit about "N Agent tool calls in a single message."
- **`step_complete_parallel` rejects with "missing execution_ids".** Main thread didn't collect all three results before calling. Re-read the skill; all N subagents must land before the parallel-step-complete.
- **Synthesize's prompt is missing one of the angles.** The dispatch_parallel → step_complete_parallel → Synthesize threading lost data. Inspect the `step_complete_parallel` call's `results` payload — each execution_id should map to a non-empty string.
- **Gather branch fails (one angle subagent calls `need`).** Entire gather fails per the Phase 2 spec; no partial results. That's by design today.
- **Two angles appear twice, one is missing.** Main thread mis-mapped execution_ids to results. Check that the `results` dict keys match the `execution_ids` array from the dispatch_parallel payload.
