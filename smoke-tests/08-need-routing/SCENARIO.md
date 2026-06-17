# Scenario 08: need-routing

## What this tests

The full need-resolve-re-dispatch loop. Verifies:

- A subagent that calls `need()` causes the MCP to return `action: "needs_resolution"` (NOT `failed`).
- The main thread reads the `reason`, provides supplemental input via `mcp__clops__resolve_need`.
- The runtime re-dispatches the same Op with a "Supplemental input" section appended to its prompt.
- The re-dispatched subagent uses the supplemental to produce a proper output and calls `complete`.
- The run completes successfully. State graph shows one execution with `attempts=2`.

## Setup

From this folder:

```bash
pip install -e ./library
claude
```

## Prompt

> Start the "TriageRequest" process with input {"message": "I can't log in"} and follow the instructions until done. When asked to resolve a need, provide {"customer_id": "cust_99"}.

## Expected behavior

1. Main thread loads the `clops-orchestration` skill.
2. Calls `mcp__clops__start_process(process="TriageRequest", input={"message": "I can't log in"})`.
3. MCP returns dispatch for TriageRequest. Subagent reads prompt, sees no `customer_id`, calls `mcp__clops__need(execution_id=…, reason="missing customer_id")`.
4. SubagentStop fires; hook allows; main calls `step_complete(run_id, <subagent's final text>)`.
5. MCP returns **`action: "needs_resolution"`** with `reason: "missing customer_id"` and an `execution_id`.
6. Per the skill, main thread decides to resolve. It calls `mcp__clops__resolve_need(run_id, execution_id, supplemental_input={"customer_id": "cust_99"})`.
7. MCP returns a new `dispatch` for the SAME execution_id. The `agent_config.prompt` includes a "Supplemental input (resolving your need)" section containing `cust_99`.
8. Re-dispatched subagent reads the supplemental, produces a triage decision like "Route to account-access because login issue with confirmed customer.", calls `complete`.
9. Main relays `step_complete`. MCP returns `{action: "done", output: <decision>}`.
10. Main reports the final decision.

## Pass criteria

- Exactly **one** `mcp__clops__need` call (the original).
- Exactly **one** `mcp__clops__resolve_need` call from the main thread.
- **Two** Agent dispatches for the SAME `execution_id` — the initial dispatch and the post-resolve re-dispatch.
- The re-dispatch prompt visibly contains `cust_99` under the "Supplemental input" section.
- Final output is a triage decision that references the customer (any team routing is acceptable as long as the subagent acknowledges the customer).
- Run ends with `action: "done"`.
- State graph has one `OpExecution` with `attempts == 2` and `need_resolved == true`.

## Common failure modes

- **Main thread treats `needs_resolution` as a failure.** Reports to user as an error without calling `resolve_need`. Check that the clops-orchestration skill is loaded and main is reading the `action` field.
- **Main thread calls `step_complete` again instead of `resolve_need`.** Returns the same `needs_resolution` payload (idempotent), main loops forever. Operator should spot this by observing repeated identical MCP tool calls.
- **Re-dispatched subagent needs again** (calls need a second time instead of using the supplemental). Runtime fails the run with `need persisted after resolution: <reason>`. This is by design — it protects against infinite resolve cycles. The subagent's prompt explicitly says not to do this.
- **Supplemental doesn't land in the re-dispatch prompt.** Check that `resolve_need` got a non-None `supplemental_input`. The prompt section is only rendered when the supplemental is present.
- **Main thread aborts instead of resolving.** That's a valid choice per the skill — run ends `aborted`. But this scenario's script asks you to resolve; if you abort, document it as a divergence.
