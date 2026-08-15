# Smoke tests

Live Claude Code sessions that validate the runtime end-to-end with human judgment. See `AGENTS.md` for the framing and conventions.

---

## One-time setup

From the repo root:

```bash
pip install -e .                    # clops + bin scripts on PATH
```

Verify:

```bash
which clops-server clops-hook clops
```

You should see three paths.

---

## Running a scenario

For each scenario:

```bash
cd smoke-tests/<n>-<slug>/
pip install -e ./library            # makes the scenario's Op library importable
claude                              # open Claude Code in this folder
```

Then paste the prompt from `SCENARIO.md` into the session and observe.

Compare what you see against the scenario's "Expected behavior" section. Pass / fail / partial is your judgment call.

### When a scenario doesn't start

| Symptom | Cause |
|---|---|
| MCP server won't connect | Wrong path in `.claude/settings.json`. Run `/mcp` in Claude Code to see server status. |
| `list_processes` returns empty | The library didn't load — check the `--library` argument matches the package you installed. |
| Subagent ends without calling `complete` | The hook should block it. If it doesn't, the `clops-hook` command path is wrong — or the hook never bound, which the server reports on stderr as `SubagentStop enforcement disabled`. |

---

## Scenarios

| # | Slug | What it tests |
|---|---|---|
| 01 | `hello-echo` | Single leaf Op. Basic relay loop: `start_process` → dispatch → `complete` → `step_complete` → done. |
| 02 | `pipeline` | `sequence(A, B)` composition. Two dispatches in order; second leaf receives first's output. |
| 03 | `tool-use` | Leaf Op with a `Tool`. Subagent invokes `call_tool` and gets the handler's result. |
| 04 | `need-path` | Subagent calls `need`. Run fails with the reason; main thread surfaces failure. |
| 05 | `branch` | `branch_on` routing. Triage emits a category; runtime picks the matched arm; unmatched arms are NOT dispatched. |
| 06 | `loop` | `loop` iteration. Seed → refine until `[done]` marker; each iteration is its own OpExecution. |
| 07 | `gather` | `gather` parallel execution. Restate topic → three angles in parallel → synthesize. Verifies `dispatch_parallel` + main-thread parallel Agent calls. |
| 08 | `need-routing` | `need` surfaces as `needs_resolution`. Main thread calls `resolve_need` with supplemental input; runtime re-dispatches same Op with supplemental section; subagent completes. |
| 11 | `subroutine` | Op invokes another Op as a subroutine capability via `call_tool`. Runtime transparently dispatches the subroutine and re-dispatches the caller with the result. Main thread sees only standard dispatch/step_complete. |
| 12 | `state` | State stores shared across a composition pipeline. ManageProject declares `tasks = Store(dict[str, Task])`; PlanTasks creates tasks in the store; ExecuteTasks reads and completes them. Validates state persistence across pipeline steps. |
| 13 | `gather-subroutine` | A dynamic sub-Op call (`call_tool`) from inside a `gather` branch. One branch defines its key term via a `DefineTerm` sub-Op while the peer branch runs concurrently; the runtime parks the calling branch, runs the subroutine, re-dispatches it, then joins in declaration order. Exercises partial gather-suspension (Slice 3). |

Each scenario is fully self-contained — no shared state, no cross-folder dependencies. Pick any one and run it in isolation.

---

## Authoring more scenarios

Read `AGENTS.md` § "How to AUTHOR a new scenario." The short version:

1. One architectural shape per scenario.
2. Smallest possible Op library.
3. Pre-wire `.claude/`.
4. Tight `SCENARIO.md` (one screen).
5. Make sure a corresponding test exists in `tests/test_simulated_e2e*.py`.
