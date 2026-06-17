# Scenario 13: gather-subroutine

## What this tests

A dynamic sub-Op call (`call_tool`) made from **inside a gather branch** — Slice 3
of the in-op flow-control work. Verifies:

- A `gather(TechnicalAngle, EconomicAngle)` round dispatches both branches in parallel.
- The `TechnicalAngle` branch calls `mcp__clops__call_tool(name="DefineTerm", ...)`
  mid-turn, while the `EconomicAngle` branch completes normally in the same round.
- The runtime keeps the `TechnicalAngle` branch's slot parked, dispatches `DefineTerm`
  as the next round, then re-dispatches `TechnicalAngle` with a "Result from DefineTerm"
  section — all **underneath the live gather**, without disturbing the completed peer.
- Once both branches truly resolve, the gather joins in declaration order
  `[TechnicalAngle, EconomicAngle]` and `Synthesize` receives the pair.

This is the partial-suspension case: a single branch detours through a subroutine
cycle while its peers run, and the join order is still preserved.

## Setup

From this folder:

```bash
pip install -e ./library
claude
```

## Prompt

> Start the "ResearchBrief" process with input "Municipal fiber-optic broadband networks" and follow the instructions until done.

## Expected behavior

1. Main thread calls `mcp__clops__start_process(process="ResearchBrief", input="Municipal fiber-optic broadband networks")`.
2. MCP returns a dispatch for `Setup`. Main runs it; `Setup` restates the topic and calls `complete`.
3. Main relays via `mcp__clops__step_complete`. MCP returns `action: "dispatch_parallel"` with TWO agent configs: `TechnicalAngle` and `EconomicAngle`. `report_via: "step_complete_parallel"`.
4. Main invokes both Agents (clops-executor) concurrently.
5. `EconomicAngle` writes its paragraph and calls `complete`.
6. `TechnicalAngle` calls `mcp__clops__call_tool(execution_id, name="DefineTerm", arguments=<the key term>)`. MCP returns `{ok: true}`. It then ends its turn (optionally calling `complete` with interim text).
7. Main relays both results via `mcp__clops__step_complete_parallel(run_id, {<technical_id>: <text>, <economic_id>: <text>})`.
8. **Runtime detects the dynamic call on the TechnicalAngle branch.** It returns ANOTHER `action: "dispatch_parallel"` containing a single config: `DefineTerm`, with the term as its input. `report_via: "step_complete_parallel"`. The EconomicAngle result is held; its branch slot waits in the join.
9. Main invokes the `DefineTerm` Agent. It returns a one-sentence definition and calls `complete`.
10. Main relays via `mcp__clops__step_complete_parallel(run_id, {<define_id>: <definition>})`.
11. **Runtime re-dispatches the TechnicalAngle branch.** Returns `action: "dispatch_parallel"` with one config: `TechnicalAngle` (same execution id as round 1), its prompt now containing a "Result from DefineTerm" section with the definition.
12. Main invokes the re-dispatched `TechnicalAngle` Agent. It writes its paragraph opening with the definition and calls `complete`.
13. Main relays via `mcp__clops__step_complete_parallel(run_id, {<technical_id>: <text>})`.
14. **Both branches now resolved.** Runtime joins them in declaration order `[technical, economic]` and returns a single dispatch for `Synthesize` (`action: "dispatch"`, `report_via: "step_complete"`).
15. Main runs `Synthesize`; it merges the two angles and calls `complete`.
16. Main relays via `mcp__clops__step_complete`. MCP returns `{action: "done"}`.

## Pass criteria

- The first gather round is a `dispatch_parallel` of exactly two branches.
- Exactly one `call_tool` call, from the `TechnicalAngle` branch, `name="DefineTerm"`.
- `DefineTerm` is dispatched as its own agent with ONLY the term as input — no TechnicalAngle or topic context leaks in.
- The re-dispatched `TechnicalAngle` prompt contains a "Result from DefineTerm" section with the definition.
- The `EconomicAngle` branch is dispatched exactly once and is NOT re-run while TechnicalAngle is mid-subroutine.
- `Synthesize` receives a list of two paragraphs in `[technical, economic]` order.
- Final output is a coherent brief citing both angles, and the technical angle reflects the definition produced by `DefineTerm`.
- Every gather-phase relay used `step_complete_parallel`; the run never errored with "called a subroutine inside a gather branch".
- No `need`, no `abort_run`.

## Common failure modes

- **Run fails with "called a subroutine inside a gather branch."** Means the Slice 3 change is missing or regressed — the old code rejected this outright.
- **TechnicalAngle writes its paragraph without calling DefineTerm.** Agents sometimes freelance. The brief would still be reasonable but wouldn't exercise the in-gather subroutine path. Re-run or nudge the prompt.
- **EconomicAngle is re-dispatched during the subroutine rounds.** Means the runtime is re-running a completed peer instead of holding its result in the join — partial suspension is broken.
- **Join order is `[economic, technical]`.** The gather must join in branch *declaration* order, not completion order. DefineTerm makes the technical branch finish last; the output must still lead with the technical angle.
- **DefineTerm's prompt contains the topic or TechnicalAngle's intent.** The subroutine boundary is leaking caller context; it should see only the term.
