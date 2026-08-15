---
name: clops-orchestration
description: Relay dispatches from the clops MCP server to subagents.
when-to-use: >
  When the user asks to run a clops process, or when start_process or
  step_complete returns a payload with action="dispatch". Load this
  skill to learn the mechanical relay loop between the MCP and the Agent tool.
---

> **Tool names below are written bare.** The clops MCP tools are namespaced by
> the server's name — usually `mcp__clops__start_process`, but a project can name
> its server something else (`mcp__clops-support__…`), and a hosted clops will.
> Call them as they appear in your available tools; the bare names here identify
> *which* tool, not how to spell it.

## How to run a process

1. Call `start_process(process=…, input=…)` with the user's requested process and input.
   - If the user doesn't know what's available, call `list_processes()` first.

2. You will receive a payload with `action`.
   - If the payload carries a top-level `system_prompt` (only the first payload of a run does), read it before you dispatch anything. It is standing project guidance for how you manage this run — e.g. how to size the agent you dispatch to a given step. Keep it in mind for every dispatch in this run. It does **not** override the mechanical relay below or license you to edit the rendered dispatch prompt (see Discipline).
   - If `action == "dispatch"`: invoke the Agent tool **once**:
     - `subagent_type`: the value of `agent_template` (always `"clops-executor"`)
     - `description`: `agent_config.description` (verbatim)
     - `prompt`: `agent_config.prompt` (verbatim)
     - `model`: `agent_config.model` (if present)
     - After the Agent returns, advance the run with `step_complete(run_id)` — **no second argument**. The subagent already reported its result to the runtime via its own `complete(...)` call, so re-passing its text here is redundant (the runtime ignores it). Only if the subagent stopped WITHOUT calling complete or need should you pass its final text as a fallback: `step_complete(run_id, <final text>)`.
   - If `action == "dispatch_parallel"`: invoke the Agent tool **N times in parallel** — one per entry in `agent_configs`. Emit all N Agent tool calls in a single message so Claude Code runs them concurrently.
     - Each subagent has its own `execution_id` baked into its prompt. The `execution_ids` array in the payload lists them in the same order as `agent_configs`.
     - Wait for ALL N subagents to return before moving on. Do not advance until you have all N final messages.
   - If `action == "needs_resolution"`: a subagent called `need()` because it couldn't proceed. The payload has `reason` and `execution_id`. Decide whether to resolve or abort:
     - **Resolve:** gather the requested information (ask the user, reason from context, call another tool), then call `resolve_need(run_id, execution_id, supplemental_input)`. Runtime re-dispatches the same Op with your supplemental attached to its prompt.
     - **Abort:** if the need can't be satisfied, call `abort_run(run_id)`.
     - Do not silently retry without providing supplemental — the subagent will just need again, and the second need after resolution fails the run.
   - If `action == "done"`: the run succeeded. Report `output` to the user.
   - If `action == "failed"`: the run failed. Report `error` to the user.

3. Report results back to the MCP — the routing is captured within step 2's branches. To summarize:
   - Single worker dispatch (`report_via: "step_complete"`): `step_complete(run_id)` — no blob; the runtime already has the subagent's output from its `complete()` call.
   - Parallel dispatch: `step_complete_parallel(run_id, results)` with a dict keyed by execution_id.
   - Needs resolution: `resolve_need(run_id, execution_id, supplemental_input)` or `abort_run(run_id)`.

4. Loop on step 2 until terminal.

## Discipline

- Do not editorialize the dispatch prompt. Do not inject additional instructions into the Agent invocation. The prompt is rendered by the MCP for a reason.
- Do not spawn Agent tool calls the MCP did not ask for. The main thread's job is mechanical relay.
- If the Agent terminates unexpectedly (stopped without calling complete or need), relay whatever final text it produced to `step_complete`; the runtime handles marking the execution failed.
