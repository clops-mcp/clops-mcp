# Smoke Test 12: State Stores

## What it tests

State stores shared across Ops in a composition pipeline:

1. `ManageProject` (composition, entry) declares `tasks = Store(dict[str, Task])`
2. `PlanTasks` (leaf, step 1) reads input, creates tasks in the store
3. `ExecuteTasks` (leaf, step 2) reads tasks from store, marks them done

## How to run

```
Run the ManageProject process with input "Build a landing page with hero section and contact form"
```

## Expected behavior

1. `start_process("ManageProject", "Build a landing page...")` returns dispatch for PlanTasks
2. PlanTasks agent:
   - Calls `mcp__clops__state(execution_id, "tasks", "set", id="task-1", value={"name": "...", "status": "pending"})` 2-3 times
   - Calls `mcp__clops__complete(execution_id, "Created N tasks: ...")`
3. `step_complete` advances to ExecuteTasks
4. ExecuteTasks agent:
   - Calls `mcp__clops__state(execution_id, "tasks", "list")` to see all tasks
   - Calls `mcp__clops__state(execution_id, "tasks", "set", id="task-1", value={"name": "...", "status": "done"})` for each
   - Calls `mcp__clops__complete(execution_id, "All tasks done: ...")`
5. `step_complete` returns `action: "done"` with the final status report

## Pass criteria

- PlanTasks successfully creates entries in the tasks store
- ExecuteTasks can read the tasks PlanTasks created (state persists across steps)
- ExecuteTasks updates task statuses
- Pipeline completes with a status report

## Common failure modes

- State not shared: ExecuteTasks sees empty tasks store (store not run-scoped)
- State tool not available: agent can't find `mcp__clops__state` (tool not registered)
- State section missing from prompt: agent doesn't know what stores exist
