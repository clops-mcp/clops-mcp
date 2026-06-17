# Scenario 11: subroutine

## What this tests

Op-as-subroutine invocation through the unified `call_tool` entry point. Verifies:

- The Op's `Tools = [SummarizeArticle]` declaration leads to SummarizeArticle appearing in the dispatched prompt under "Capabilities available to you."
- The subagent invokes `mcp__clops__call_tool(execution_id, name="SummarizeArticle", arguments={...})` with the article text.
- The runtime records the pending subroutine, and `step_complete` dispatches SummarizeArticle as a fresh agent with clean context.
- SummarizeArticle completes; the next `step_complete` re-dispatches PrepareBriefing with a "Result from SummarizeArticle" section in its prompt.
- PrepareBriefing uses the summary to compose the briefing and calls `complete`.

This is the core subroutine pattern: an Op delegates work to another Op at runtime, the runtime handles dispatch/resume transparently, and the main thread never knows subroutines are involved (just its standard dispatch → step_complete loop).

## Setup

From this folder:

```bash
pip install -e ./library
claude
```

## Prompt

> Start the "PrepareBriefing" process with input "Researchers at MIT announced a breakthrough in room-temperature superconductivity using a novel hydrogen-rich compound. The material, designated LK-99b, demonstrated zero electrical resistance at 22 degrees Celsius under ambient pressure during laboratory tests. If confirmed by independent teams, this could transform power transmission, computing, and transportation. Critics note the sample size was small and the measurement window was brief. Three independent labs are attempting replication, with results expected within weeks." and follow the instructions until done.

## Expected behavior

1. Main thread calls `mcp__clops__start_process(process="PrepareBriefing", input=<article>)`.
2. MCP returns dispatch for PrepareBriefing. Prompt includes "Capabilities available to you" listing `SummarizeArticle` with its Input/Output descriptions.
3. Main invokes Agent (clops-executor) for PrepareBriefing.
4. PrepareBriefing subagent calls `mcp__clops__call_tool(execution_id, name="SummarizeArticle", arguments=<article text>)`. MCP returns `{ok: true}`.
5. PrepareBriefing subagent calls `mcp__clops__complete(execution_id, output=<interim>)` and ends its turn.
6. Main relays via `mcp__clops__step_complete(run_id, <text>)`.
7. **Runtime internally detects pending subroutine.** Returns dispatch for SummarizeArticle — a fresh agent with only the article text as input. No PrepareBriefing context leaks in.
8. Main invokes Agent (clops-executor) for SummarizeArticle.
9. SummarizeArticle produces a 2-3 sentence summary, calls `mcp__clops__complete`.
10. Main relays via `mcp__clops__step_complete(run_id, <text>)`.
11. **Runtime internally detects subroutine child.** Re-dispatches PrepareBriefing with a "Result from SummarizeArticle" section containing the summary.
12. Main invokes Agent (clops-executor) for PrepareBriefing (re-dispatch).
13. PrepareBriefing uses the summary to compose the briefing note and recommendation, calls `mcp__clops__complete`.
14. Main relays via `mcp__clops__step_complete`. MCP returns `{action: "done"}`.

## Pass criteria

- One `call_tool` call from PrepareBriefing with `name="SummarizeArticle"`.
- Three total Agent dispatches: PrepareBriefing (turn 1), SummarizeArticle, PrepareBriefing (turn 2 with result).
- Three `step_complete` calls from the main thread — all via the same standard relay.
- SummarizeArticle's prompt does NOT contain PrepareBriefing's intent or context (clean boundary).
- PrepareBriefing's second dispatch prompt contains a "Result from SummarizeArticle" section.
- Final output is a briefing note that references the summary content (superconductivity, LK-99b, replication).
- Final output includes a recommendation on whether to read the full article.
- No `need`, no `abort_run`, no new MCP tools used.
- Main thread used only `start_process` and `step_complete` — never called any subroutine-specific tool.

## Common failure modes

- **PrepareBriefing summarizes the article itself without calling call_tool.** Intent says to use SummarizeArticle, but agents sometimes freelance. The briefing would still be reasonable but wouldn't exercise the subroutine path.
- **PrepareBriefing calls `call_tool("SummarizeArticle", ...)` but doesn't call `complete`.** The SubagentStop hook should still release (call_op sets completed_flag), but the agent's final text may be sparse. step_complete proceeds normally regardless.
- **SummarizeArticle's prompt contains PrepareBriefing context.** Means the prompt renderer is leaking caller state — the subroutine should only see its own Intent and the article input.
- **Main thread tries to call a subroutine-specific tool.** If the main thread calls something like `subroutine_result`, the MCP should return an unknown-tool error. The main thread should only ever use `step_complete`.
- **Runtime doesn't detect pending subroutine in step_complete.** The first step_complete would advance the run normally (treating PrepareBriefing as done), skipping the subroutine entirely. Symptom: only one Agent dispatch, final output is PrepareBriefing's interim text.
