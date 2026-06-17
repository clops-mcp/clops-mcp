# clops Quickstart

## Testing the Hello-Echo Smoke Test

### Prerequisites (Already Done)
- clops installed in `.venv`
- smoke_01_echo library installed
- settings.json updated with correct paths

### Step 1: Open a new terminal

```bash
cd /Users/wesley/code/clops/smoke-tests/01-hello-echo
```

### Step 2: Start Claude Code

```bash
claude
```

This starts a new Claude Code session that will:
- Read `.claude/settings.json` from the current directory
- Start the `clops` MCP server (`clops-server --library smoke_01_echo`)
- Register the SubagentStop hook

### Step 3: Run the test prompt

In Claude Code, type:

```
Run the Echo process with the input "hello world"
```

### What Should Happen

1. **Main thread** sees "Echo process" and loads the `clops-orchestration` skill
2. **Main thread** calls `mcp__clops__start_process(process="Echo", input="hello world")`
3. **MCP server** returns a dispatch instruction with:
   - `action: "dispatch"`
   - `agent_template: "clops-executor"`
   - `agent_config` containing the prompt for the Echo Op
4. **Main thread** spawns a subagent using the Agent tool with the provided config
5. **Subagent** executes, sees its `execution_id`, and calls `mcp__clops__complete(execution_id=..., output="echo: hello world")`
6. **SubagentStop hook** fires, which is a no-op since `complete` was called
7. **Main thread** receives subagent result, calls `mcp__clops__step_complete(run_id, result)`
8. **MCP server** returns `{action: "done", output: "echo: hello world"}`
9. **Main thread** reports the output to you

### Success Criteria

- You see one `start_process` call
- You see one Agent tool dispatch
- You see one `complete` call from the subagent
- You see one `step_complete` call from main thread
- Final output contains "echo: hello world"

### Troubleshooting

**MCP server fails to connect:**
- Check that the path in settings.json is correct
- Run `/mcp` in Claude Code to see server status

**`list_processes` returns empty:**
- The library wasn't loaded - check `--library smoke_01_echo` arg

**Subagent terminates without calling `complete`:**
- Hook should block; if it doesn't, the hook command path is wrong

---

## Next Steps

Once hello-echo works, try the other smoke tests in order:
- `02-pipeline` - Tests `sequence()` composition
- `03-tool-use` - Tests Tool invocation
- `04-need-path` - Tests the "need" error/retry path
- etc.
