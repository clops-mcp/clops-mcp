# Scenario 05: branch

## What this tests

`branch_on` execution. Verifies:

- A composition that routes via `branch_on` actually picks the matched arm at runtime.
- The unmatched arms are NOT dispatched.
- The branch's key function operates on the upstream Op's prose output.
- The matched arm receives the upstream output as its input.

## Setup

From this folder:

```bash
pip install -e ./library
claude
```

## Prompt

> Start the "Route" process with input "I was double charged last month, please refund" and follow the instructions until done.

## Expected behavior

1. Main thread loads the `clops-orchestration` skill.
2. Calls `mcp__clops__start_process(process="Route", input="I was double charged last month, please refund")`.
3. MCP returns dispatch instruction for **Triage**.
4. Triage subagent reads the message, calls `complete` with output `"billing"` (one word, lowercase).
5. Main thread relays `step_complete`. The runtime evaluates the branch's key function on `"billing"`, picks the `HandleBilling` arm, returns a new dispatch.
6. MCP returns dispatch for **HandleBilling**. The dispatch's `agent_config.description` should start with "Execute HandleBilling" — NOT HandleTechnical, NOT HandleGeneral.
7. HandleBilling subagent emits a one-sentence billing acknowledgment, calls `complete`.
8. Main thread relays `step_complete`. MCP returns `{action: "done", output: <the reply>}`.
9. Main thread reports the reply to the user.

## Pass criteria

- Exactly **two** Agent dispatches: Triage, then HandleBilling.
- The second dispatch's description contains `HandleBilling`.
- HandleTechnical and HandleGeneral were never dispatched. (You can verify by counting Agent invocations in the session.)
- Final user-facing reply acknowledges the billing issue.
- No `mcp__clops__call_tool`, no `need`, no `abort_run`.
- No SubagentStop block messages.

## Common failure modes

- **Triage emits more than the category word.** The branch's key function does substring matching, so "I think this is a billing issue" still matches `"billing"`. But the Intent says "exactly one word" — a misbehaving subagent that ignores that is still likely to land on a category and route correctly. If routing fails, check the Intent.
- **`No arm for branch key …` failure.** The triage subagent emitted something that doesn't contain billing/technical/general (e.g. "refund"). Either the Intent isn't constraining enough or the key function's substring search needs more keywords.
- **All three arms dispatched.** Bug in the runtime — branch_on isn't actually selecting one. File this immediately.
- **Only Triage dispatched, then `done`.** The branch_on isn't being walked at all. Check that the runtime includes the branch_on execution path (`_resolve_branch` in `clops/runtime/core.py`).
