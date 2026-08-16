# Scenario 01: hello-echo

## What this tests

The simplest possible process: one leaf Op, one dispatch, one round-trip. Verifies the basic `start_process` → dispatch → `complete` → `step_complete` → done relay loop works end-to-end through a real Claude Code session.

## Setup

From this folder:

```bash
pip install -e ./library
```

Then start a fresh Claude Code session here:

```bash
claude
```

## Prompt

> Start the "Echo" process with input "hello world" and follow the instructions until done.

## Expected behavior

1. Main thread (you, the agent) loads the `clops-orchestration` skill (semantic match on "Echo process").
2. Calls `mcp__clops__start_process(process="Echo", input="hello world")`.
   - The MCP returns a payload with `action: "dispatch"`, `agent_template: "clops-executor"`, and an `agent_config` containing the prompt for the Echo Op.
3. Invokes the Agent tool: `subagent_type="clops-executor"`, `description` and `prompt` copied verbatim from `agent_config`.
4. The clops-executor subagent reads its prompt, sees its `execution_id`, and calls `mcp__clops__complete(execution_id=…, output="echo: hello world")` (or close — the agent may add minimal styling but should keep the `echo: ` prefix).
5. After the subagent terminates, main thread calls `mcp__clops__step_complete(run_id, <subagent's final text>)`.
6. The MCP returns `{action: "done", output: "echo: hello world"}`.
7. Main thread reports the output to the user.

You should see the Echo Op dispatched **exactly once**, and the final output should contain `echo:` followed by `hello world` (case may vary; the exact text may have minor variation — that's fine, the mechanics are what we're testing).

## Pass criteria

- One `mcp__clops__start_process` call.
- One Agent tool call dispatching `clops-executor`.
- One `mcp__clops__complete` call from the subagent.
- One `mcp__clops__step_complete` call from the main thread.
- Final output reaches the user, contains the echo of "hello world".
- No SubagentStop hook block messages.
- No additional MCP tool calls (no `call_tool`, no `need`, no `abort_run`).

## Common failure modes

- **MCP server fails to start.** Check `.claude/settings.json` and that `clops-mcp` is on PATH. Run `pip install -e ./library` if you haven't.
- **`list_processes` returns empty.** The library wasn't loaded — check the `--library smoke_01_echo` arg in `settings.json` matches the installed package name.
- **Subagent terminates without calling `complete`.** Hook should block; you'll see Claude Code surface the block reason. If it doesn't block, the SubagentStop hook isn't wired up — check `clops-hook` is on PATH.
- **Subagent calls `mcp__clops__call_tool` despite no tools being declared.** Symptom that the prompt's "Tools available" section is leaking. Should not happen — Echo declares no Tools.
