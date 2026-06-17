# Scenario 04: need-path

## What this tests

The subagent's `need(reason)` escape hatch. Verifies:

- A leaf Op given malformed input correctly recognizes it cannot proceed and calls `mcp__clops__need(execution_id, reason)` instead of `complete`.
- The runtime marks the execution failed with the reason as the error.
- `step_complete` returns `{action: "failed", error: …}`.
- The SubagentStop hook still allows the subagent to terminate (need flips `completed_flag` so the queue-release succeeds).
- The main thread surfaces the failure to the user with the reason intact.

## Setup

From this folder:

```bash
pip install -e ./library
claude
```

## Prompt

> Start the "TriageRequest" process with input {"message": "I need help"} and follow the instructions until done.

## Expected behavior

1. Main thread loads the `clops-orchestration` skill.
2. Calls `mcp__clops__start_process(process="TriageRequest", input={"message": "I need help"})`.
3. MCP returns dispatch instruction. The prompt's `## Your input` section shows the input dict (no customer_id).
4. Main thread invokes Agent (clops-executor).
5. Subagent reads its prompt, sees the input lacks `customer_id`, and per the Intent instruction calls `mcp__clops__need(execution_id=…, reason="missing customer_id")`.
6. Subagent terminates. SubagentStop hook fires; runtime releases the queued completion (need set `completed_flag=True`); hook returns `{}` (allow). No block message.
7. Main thread relays via `mcp__clops__step_complete(run_id, …)`.
8. MCP returns `{action: "failed", error: "need: missing customer_id"}` (or a near variant — the substring "missing customer_id" should be in the error).
9. Main thread reports the failure to the user with the reason.

## Pass criteria

- Subagent calls `mcp__clops__need`, **not** `mcp__clops__complete`.
- The reason passed to `need` mentions `customer_id` (literal "missing customer_id" preferred per the Intent, but minor wording variation OK).
- `step_complete` returns `action: "failed"`.
- Final user-facing message conveys: the run failed, and why.
- No SubagentStop block message (`need` should satisfy the hook just like `complete` does).
- One Agent dispatch only.

## Common failure modes

- **Subagent invents a customer_id and proceeds.** The Intent is explicit about not proceeding without one. If this happens, sharpen the Intent or escalate — the subagent ignored explicit instructions.
- **Subagent calls `complete` with an excuse instead of `need`.** Wrong escape hatch. The runtime treats this as a successful step; the run "succeeds" with garbage output. The Intent should make the choice unambiguous.
- **SubagentStop hook BLOCKS after `need`.** Bug — `need` is supposed to flip `completed_flag` exactly like `complete` does. If this happens, check `Runtime.need` in `clops/runtime/core.py`.
- **`step_complete` returns `done` instead of `failed`.** Likely the subagent called `complete` instead of `need`, or the runtime didn't capture the need state.
