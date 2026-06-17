---
name: clops-orchestration
description: Relay dispatches from the clops MCP server to subagents.
when-to-use: >
  When the user asks to run a clops process, or when mcp__clops__start_process or
  mcp__clops__step_complete returns a payload with action="dispatch". Load this
  skill to learn the mechanical relay loop between the MCP and the Agent tool.
---

## How to run a process

1. Call `mcp__clops__start_process(process=…, input=…)` with the user's requested process and input.
   - If the user doesn't know what's available, call `mcp__clops__list_processes()` first.

2. You will receive a payload with `action`.
   - If `action == "dispatch"`: invoke the Agent tool **once**:
     - `subagent_type`: the value of `agent_template` (always `"clops-executor"`)
     - `description`: `agent_config.description` (verbatim)
     - `prompt`: `agent_config.prompt` (verbatim)
     - `model`: `agent_config.model` (if present)
     - After the Agent returns:
       - If the payload has `report_via == "teammate_response"`, the subagent was a teammate — it didn't (and shouldn't) call `mcp__clops__complete`. Relay its final text via `mcp__clops__teammate_response(run_id, execution_id, <final text>)`. The `execution_id` for teammate dispatches is surfaced at the top level of the dispatch payload.
       - Otherwise (`report_via == "step_complete"` or absent), relay via `mcp__clops__step_complete(run_id, <final text>)`.
   - If `action == "dispatch_parallel"`: invoke the Agent tool **N times in parallel** — one per entry in `agent_configs`. Emit all N Agent tool calls in a single message so Claude Code runs them concurrently.
     - Each subagent has its own `execution_id` baked into its prompt. The `execution_ids` array in the payload lists them in the same order as `agent_configs`.
     - Wait for ALL N subagents to return before moving on. Do not advance until you have all N final messages.
   - If `action == "dispatch_teammate_message"`: a worker called `send()` to message a teammate. Dispatch the teammate agent exactly like a `"dispatch"` action. After it returns, relay via `mcp__clops__teammate_response(run_id, execution_id, <final text>)` using the top-level `execution_id` from the payload (this is the teammate's ID, not the worker's). The runtime will then re-dispatch the worker with the teammate's response attached.
   - If `action == "needs_resolution"`: a subagent called `need()` because it couldn't proceed. The payload has `reason` and `execution_id`. Decide whether to resolve or abort:
     - **Resolve:** gather the requested information (ask the user, reason from context, call another tool), then call `mcp__clops__resolve_need(run_id, execution_id, supplemental_input)`. Runtime re-dispatches the same Op with your supplemental attached to its prompt.
     - **Abort:** if the need can't be satisfied, call `mcp__clops__abort_run(run_id)`.
     - Do not silently retry without providing supplemental — the subagent will just need again, and the second need after resolution fails the run.
   - If `action == "done"`: the run succeeded. Report `output` to the user.
   - If `action == "failed"`: the run failed. Report `error` to the user.

3. Report results back to the MCP — the routing is captured within step 2's branches. To summarize:
   - Single worker dispatch (`report_via: "step_complete"`): `mcp__clops__step_complete(run_id, <final text>)`.
   - Teammate dispatch (`report_via: "teammate_response"`): `mcp__clops__teammate_response(run_id, execution_id, <final text>)`.
   - Parallel dispatch: `mcp__clops__step_complete_parallel(run_id, results)` with a dict keyed by execution_id.
   - Needs resolution: `mcp__clops__resolve_need(run_id, execution_id, supplemental_input)` or `mcp__clops__abort_run(run_id)`.

4. Loop on step 2 until terminal.

## Discipline

- Do not editorialize the dispatch prompt. Do not inject additional instructions into the Agent invocation. The prompt is rendered by the MCP for a reason.
- Do not spawn Agent tool calls the MCP did not ask for. The main thread's job is mechanical relay.
- If the Agent terminates unexpectedly (stopped without calling complete or need), relay whatever final text it produced to `step_complete`; the runtime handles marking the execution failed.
