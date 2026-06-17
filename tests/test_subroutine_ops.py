"""Tests for subroutine Ops (v1): Op-as-capability via unified call_tool.

Covers: Op validation in Tools list, call_op logic (depth, cycles, leaf-only,
mutual exclusivity), step_complete routing (caller side + child side),
prompt rendering, and cancellation propagation.
"""

from __future__ import annotations

import json
import pytest

from clops import Concept, Op, Tool
from clops.registry import registry
from clops.runtime.core import Runtime, RuntimeError_
from clops.runtime.dispatch import render_prompt
from clops.runtime.mcp_server import FlowServer, ServerConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    # Re-register module-level Ops/Tools/Concepts that were cleared.
    # Registration happens at class-def time; after clear we must
    # manually re-register the ones this module defined.
    for cls in (TextIn, TextOut, SummaryOut, Summarizer, DeepAnalyzer, Briefer):
        registry.register_op(cls) if issubclass(cls, Op) else None
    # Concepts auto-register via ConceptMeta but registry.clear() wipes them.
    # Tools re-register via __post_init__ on creation, but we only have one
    # module-level instance that was created once. Re-register it.
    registry._tools[word_count_tool.name] = word_count_tool
    yield
    registry.clear()


def _decode(response) -> dict:
    return json.loads(response[0].text)


def _exec_id_from(dispatch: dict) -> str:
    prompt = dispatch["agent_config"]["prompt"]
    marker = "execution_id is `"
    start = prompt.index(marker) + len(marker)
    end = prompt.index("`", start)
    return prompt[start:end]


# ---------------------------------------------------------------------------
# Shared Op definitions
# ---------------------------------------------------------------------------

class TextIn(Concept):
    description = "Raw text input."

class TextOut(Concept):
    description = "Processed text output."

class SummaryOut(Concept):
    description = "A condensed summary."


def _word_count(text: str = "") -> dict:
    return {"count": len(text.split())}

word_count_tool = Tool(
    name="word_count",
    description="Count words.",
    parameters={"text": str},
    handler=_word_count,
)


class Summarizer(Op):
    Input = TextIn
    Output = SummaryOut
    Intent = "Summarize the text in 1-2 sentences."
    Meta = "Reusable summarization subroutine."


class DeepAnalyzer(Op):
    Input = TextIn
    Output = TextOut
    Intent = "Analyze text deeply."
    Meta = "Analysis Op that itself can call subroutines."
    Tools = [Summarizer]


class Briefer(Op):
    Input = TextIn
    Output = TextOut
    Intent = "Produce a briefing using summarization."
    Meta = "Tests the subroutine pattern."
    Tools = [word_count_tool, Summarizer]
    entry = True


# ---------------------------------------------------------------------------
# 1. Op validation: Op in Tools list accepted
# ---------------------------------------------------------------------------

def test_op_in_tools_list_accepted():
    """An Op class in the Tools list passes validation."""
    # Briefer and DeepAnalyzer were defined without error above.
    assert Summarizer in Briefer.Tools
    assert Summarizer in DeepAnalyzer.Tools


# ---------------------------------------------------------------------------
# 2. Op validation: non-Op/non-Tool rejected
# ---------------------------------------------------------------------------

def test_non_op_non_tool_in_tools_rejected():
    with pytest.raises(TypeError, match="Tools\\[0\\] must be a Tool instance or an Op class"):
        class Bad(Op):
            Input = TextIn
            Output = TextOut
            Intent = "Bad."
            Meta = "Testing invalid Tools entry."
            Tools = ["not_a_tool"]


# ---------------------------------------------------------------------------
# 3. call_op rejects composition subroutines
# ---------------------------------------------------------------------------

def test_call_op_composite_callee_runs_in_same_run():
    """A composite callee runs its body as a sub-flow in the *same* run (shared
    stores), beneath the caller's parked slot — not as an isolated child run."""
    from clops import sequence

    class Inner(Op):
        Input = TextIn
        Output = TextOut
        Intent = "Inner step."
        Meta = "Inner."

    class CompositionSub(Op):
        Input = TextIn
        Output = TextOut
        Intent = "A composition."
        Meta = "Composite callee."
        body = sequence(Inner)

    class Caller(Op):
        Input = TextIn
        Output = TextOut
        Intent = "Caller."
        Meta = "Caller."
        Tools = [CompositionSub]
        entry = True

    rt = Runtime()
    d = rt.start("Caller", "hello")
    run_id = d["run_id"]
    caller_id = _exec_id_from(d)

    # The composite callee is accepted and recorded as a pending invoke.
    assert rt.call_op(caller_id, "CompositionSub", CompositionSub, "hello")["ok"] is True
    caller = rt.get_run(run_id).get_execution(caller_id)
    assert caller.pending_invoke == ("CompositionSub", CompositionSub, "hello")

    # Caller ends its turn → the composite's body (Inner) dispatches in the
    # SAME run, not a child run.
    d2 = rt.step_complete(run_id, None)
    assert d2["action"] == "dispatch"
    assert d2["run_id"] == run_id
    assert d2["agent_config"]["description"].startswith("Execute Inner")

    # Inner completes → composite returns → caller re-dispatched with the result.
    inner_id = _exec_id_from(d2)
    rt.complete(inner_id, "inner-out")
    redispatch = rt.step_complete(run_id, "inner-out")
    assert redispatch["action"] == "dispatch"
    assert redispatch["run_id"] == run_id
    assert redispatch["agent_config"]["description"].startswith("Execute Caller")
    assert "inner-out" in redispatch["agent_config"]["prompt"]

    # Caller finishes → run done.
    rt.complete(caller_id, "final")
    done = rt.step_complete(run_id, "final")
    assert done["action"] == "done"
    assert done["output"] == "final"


# ---------------------------------------------------------------------------
# 4. call_op creates child execution
# ---------------------------------------------------------------------------

def test_call_op_records_invoke_and_dispatches_child():
    rt = Runtime()
    d = rt.start("Briefer", "some text")
    exec_id = _exec_id_from(d)
    run = rt.get_run(d["run_id"])

    result = rt.call_op(exec_id, "Summarizer", Summarizer, "some text")
    assert result["ok"] is True

    # The call is recorded as a pending invoke on the caller; no child execution
    # exists yet (it materializes when the leaf's turn is serviced).
    caller_exec = run.get_execution(exec_id)
    assert caller_exec.pending_invoke == ("Summarizer", Summarizer, "some text")
    assert caller_exec.invoke_count == 1

    # Caller ends its turn → the child (Summarizer) is dispatched, parented to
    # the caller at depth 1.
    d2 = rt.step_complete(run.id, "interim")
    assert d2["action"] == "dispatch"
    child_id = _exec_id_from(d2)
    child_exec = run.get_execution(child_id)
    assert child_exec.op_name == "Summarizer"
    assert child_exec.caller_execution_id == exec_id
    assert child_exec.subroutine_depth == 1
    assert child_exec.input_snapshot == "some text"


# ---------------------------------------------------------------------------
# 5. Depth limit enforced
# ---------------------------------------------------------------------------

def test_depth_limit_enforced():
    """Chain of 4 with default limit 3 should fail."""
    class L1(Op):
        Input = TextIn; Output = TextOut
        Intent = "Level 1."; Meta = "Depth test."
        entry = True

    class L2(Op):
        Input = TextIn; Output = TextOut
        Intent = "Level 2."; Meta = "Depth test."
        Tools = [Summarizer]

    class L3(Op):
        Input = TextIn; Output = TextOut
        Intent = "Level 3."; Meta = "Depth test."
        Tools = [Summarizer]

    rt = Runtime(max_subroutine_depth=3)
    d = rt.start("L1", "hi")
    exec_id = _exec_id_from(d)
    run = rt.get_run(d["run_id"])

    # Push the caller to the configured depth limit; one more call fails.
    caller = run.get_execution(exec_id)
    caller.subroutine_depth = 3  # at the configured limit

    with pytest.raises(RuntimeError_, match="depth limit exceeded"):
        rt.call_op(exec_id, "Summarizer", Summarizer, "hi")


def test_call_budget_enforced():
    """A caller that exhausts its per-execution dynamic-call budget is rejected,
    even though its nesting depth stays constant (the loop case)."""
    class Looper(Op):
        Input = TextIn; Output = TextOut
        Intent = "Calls a sub-Op repeatedly."; Meta = "Budget test."
        Tools = [Summarizer]
        entry = True

    rt = Runtime(max_invokes_per_execution=2)
    d = rt.start("Looper", "hi")
    exec_id = _exec_id_from(d)
    run = rt.get_run(d["run_id"])

    # Two calls are within budget (depth stays 1 each time — loop-stable). Each
    # call_op increments invoke_count; the budget bounds the count regardless of
    # whether the prior invoke has been serviced.
    rt.call_op(exec_id, "Summarizer", Summarizer, "a")
    caller = run.get_execution(exec_id)
    assert caller.invoke_count == 1
    assert caller.subroutine_depth == 0  # caller is the entry Op; never nested
    rt.call_op(exec_id, "Summarizer", Summarizer, "b")
    assert caller.invoke_count == 2

    # The third call exceeds the budget of 2.
    with pytest.raises(RuntimeError_, match="budget exhausted"):
        rt.call_op(exec_id, "Summarizer", Summarizer, "c")


def test_call_budget_recoverable_via_need():
    """Exhausting the dynamic-call budget is recoverable: the agent need()s,
    the main thread resolves it, and the budget is refreshed so it can continue."""
    class Looper(Op):
        Input = TextIn; Output = TextOut
        Intent = "Loops."; Meta = "Budget-need recovery test."
        Tools = [Summarizer]
        entry = True

    rt = Runtime(max_invokes_per_execution=1)
    d = rt.start("Looper", "hi")
    run_id = d["run_id"]
    exec_id = _exec_id_from(d)
    caller = rt.get_run(run_id).get_execution(exec_id)

    # Turn 1: one call within budget. Service it fully (Summarizer runs, Looper
    # re-dispatched) so the caller is back on a fresh turn.
    rt.call_op(exec_id, "Summarizer", Summarizer, "a")
    d2 = rt.step_complete(run_id, "interim")
    assert d2["agent_config"]["description"].startswith("Execute Summarizer")
    sub_id = _exec_id_from(d2)
    rt.complete(sub_id, "summary")
    d3 = rt.step_complete(run_id, "summary")
    assert d3["agent_config"]["description"].startswith("Execute Looper")
    assert caller.invoke_count == 1

    # Turn 2: the next call exhausts the budget of 1 and flags the execution.
    with pytest.raises(RuntimeError_, match="budget exhausted"):
        rt.call_op(exec_id, "Summarizer", Summarizer, "b")
    assert caller.budget_exhausted is True

    # The agent escalates via need(); the main thread resolves it, refreshing
    # the budget and re-dispatching the caller with the supplemental.
    rt.need(exec_id, "I need more sub-Op calls to finish.")
    surfaced = rt.step_complete(run_id, "need: more")
    assert surfaced["action"] == "needs_resolution"
    redispatch = rt.resolve_need(run_id, exec_id, "approved — keep going")
    assert redispatch["action"] == "dispatch"
    assert caller.budget_exhausted is False
    assert caller.invoke_budget_grant == 1

    # The agent can call again now (effective budget 1 + 1 = 2).
    rt.call_op(exec_id, "Summarizer", Summarizer, "c")
    assert caller.invoke_count == 2


# ---------------------------------------------------------------------------
# 6. Cycle detection
# ---------------------------------------------------------------------------

def test_cycle_detection():
    class CycleA(Op):
        Input = TextIn; Output = TextOut
        Intent = "A."; Meta = "Cycle test."
        entry = True

    # CycleA calls CycleB, CycleB calls CycleA → cycle
    rt = Runtime()
    d = rt.start("CycleA", "hi")
    exec_id_a = _exec_id_from(d)
    run = rt.get_run(d["run_id"])

    # Simulate: A called B, now B tries to call A.
    # Create a fake B execution that was called by A.
    from clops.runtime.state import OpExecution, ExecutionStatus
    exec_b = OpExecution(
        id="exec_fake_b",
        op_name="CycleB",
        run_id=run.id,
        input_snapshot="hi",
        kind="worker",
        status=ExecutionStatus.RUNNING,
        subroutine_depth=1,
        caller_execution_id=exec_id_a,
    )
    # Give B the CycleA subroutine in its Tools (normally via Op class)
    run.add_execution(exec_b)
    run.pending_executions.add("exec_fake_b")

    with pytest.raises(RuntimeError_, match="cycle detected.*CycleA"):
        rt.call_op("exec_fake_b", "CycleA", CycleA, "hi")


# ---------------------------------------------------------------------------
# 8. step_complete: caller side — dispatches subroutine
# ---------------------------------------------------------------------------

def test_step_complete_dispatches_subroutine():
    rt = Runtime()
    d = rt.start("Briefer", "some text")
    exec_id = _exec_id_from(d)
    run_id = d["run_id"]

    # Agent calls call_op
    rt.call_op(exec_id, "Summarizer", Summarizer, "some text")

    # Agent's turn ends, main thread relays
    d2 = rt.step_complete(run_id, "interim output")

    assert d2["action"] == "dispatch"
    assert d2["report_via"] == "step_complete"
    # The dispatched agent should be Summarizer
    assert "Summarizer" in d2["agent_config"]["description"]
    assert "Summarize the text" in d2["agent_config"]["prompt"]


# ---------------------------------------------------------------------------
# 9. step_complete: child side — re-dispatches caller
# ---------------------------------------------------------------------------

def test_step_complete_redispatches_caller():
    rt = Runtime()
    d = rt.start("Briefer", "some text")
    caller_exec_id = _exec_id_from(d)
    run_id = d["run_id"]

    # Agent calls call_op, then turn ends
    rt.call_op(caller_exec_id, "Summarizer", Summarizer, "some text")
    d2 = rt.step_complete(run_id, "interim")

    # Subroutine agent completes
    sub_exec_id = _exec_id_from(d2)
    rt.complete(sub_exec_id, "This is a summary of the text.")

    # Main thread relays subroutine result
    d3 = rt.step_complete(run_id, "This is a summary of the text.")

    assert d3["action"] == "dispatch"
    assert d3["report_via"] == "step_complete"
    # The re-dispatched agent should be Briefer with the result
    assert "Briefer" in d3["agent_config"]["description"]
    assert "Result from Summarizer" in d3["agent_config"]["prompt"]
    assert "This is a summary of the text." in d3["agent_config"]["prompt"]


# ---------------------------------------------------------------------------
# 10. Full round trip
# ---------------------------------------------------------------------------

def test_full_round_trip():
    rt = Runtime()
    d1 = rt.start("Briefer", "article text here")
    caller_exec_id = _exec_id_from(d1)
    run_id = d1["run_id"]

    # Step 1: Caller dispatched. Agent calls call_op + complete.
    rt.call_op(caller_exec_id, "Summarizer", Summarizer, "article text here")
    rt.complete(caller_exec_id, "Requested summarization")
    d2 = rt.step_complete(run_id, "Requested summarization")
    assert d2["action"] == "dispatch"  # subroutine dispatch

    # Step 2: Subroutine runs and completes.
    sub_exec_id = _exec_id_from(d2)
    rt.complete(sub_exec_id, "Summary: key points from article.")
    d3 = rt.step_complete(run_id, "Summary: key points from article.")
    assert d3["action"] == "dispatch"  # caller re-dispatch

    # Step 3: Caller re-dispatched with result, completes.
    redispatch_exec_id = _exec_id_from(d3)
    assert redispatch_exec_id == caller_exec_id  # same execution re-dispatched
    rt.complete(caller_exec_id, "Final briefing based on summary.")
    d4 = rt.step_complete(run_id, "Final briefing based on summary.")
    assert d4["action"] == "done"
    assert d4["output"] == "Final briefing based on summary."


# ---------------------------------------------------------------------------
# 11. Prompt: flat capabilities list
# ---------------------------------------------------------------------------

def test_prompt_renders_flat_capabilities():
    prompt = render_prompt(
        Briefer, "test input", execution_id="exec_test"
    )
    assert "## Capabilities available to you" in prompt
    assert "`word_count`" in prompt
    assert "`Summarizer`" in prompt
    assert "call_tool" in prompt
    # Should NOT have separate subsection headers
    assert "## Tools available to you" not in prompt
    assert "### Programmatic tools" not in prompt
    assert "### Subroutine Ops" not in prompt


# ---------------------------------------------------------------------------
# 12. Prompt: result section
# ---------------------------------------------------------------------------

def test_prompt_renders_subroutine_result():
    prompt = render_prompt(
        Briefer,
        "test input",
        execution_id="exec_test",
        pending_subroutine_result={
            "op_name": "Summarizer",
            "output": "The summary content here.",
        },
    )
    assert "## Result from Summarizer" in prompt
    assert "The summary content here." in prompt
    assert "call `complete`" in prompt


# ---------------------------------------------------------------------------
# 13. call_tool routing (via MCP server)
# ---------------------------------------------------------------------------

def test_call_tool_routes_correctly():
    srv = FlowServer(ServerConfig())
    d = srv._handle_start_process({"process": "Briefer", "input": "hi"})
    exec_id = _exec_id_from(d)

    # Programmatic tool: returns result immediately
    result = srv._handle_call_tool({
        "execution_id": exec_id,
        "name": "word_count",
        "arguments": {"text": "hello world"},
    })
    assert result == {"count": 2}

    # Op subroutine: returns {ok: true}
    result2 = srv._handle_call_tool({
        "execution_id": exec_id,
        "name": "Summarizer",
        "arguments": {"text": "some article"},
    })
    assert result2["ok"] is True

    # Unknown: raises error
    with pytest.raises(RuntimeError_, match="did not declare tool"):
        srv._handle_call_tool({
            "execution_id": exec_id,
            "name": "nonexistent",
        })


# ---------------------------------------------------------------------------
# 14. Cancellation propagates
# ---------------------------------------------------------------------------

def test_cancellation_propagates():
    rt = Runtime()
    d = rt.start("Briefer", "text")
    caller_exec_id = _exec_id_from(d)
    run_id = d["run_id"]

    # Caller calls subroutine, step_complete dispatches it
    rt.call_op(caller_exec_id, "Summarizer", Summarizer, "text")
    d2 = rt.step_complete(run_id, "interim")
    sub_exec_id = _exec_id_from(d2)

    # Abort while subroutine is running
    rt.abort(run_id)

    run = rt.get_run(run_id)
    caller = run.get_execution(caller_exec_id)
    child = run.get_execution(sub_exec_id)

    # Both should be failed
    assert caller.status.value == "failed"
    assert caller.error == "Run aborted"
    assert child.status.value == "failed"
    assert child.error == "Run aborted"


# ---------------------------------------------------------------------------
# 15. Subroutine need fails run
# ---------------------------------------------------------------------------

def test_subroutine_need_fails_run():
    rt = Runtime()
    d = rt.start("Briefer", "text")
    caller_exec_id = _exec_id_from(d)
    run_id = d["run_id"]

    rt.call_op(caller_exec_id, "Summarizer", Summarizer, "text")
    d2 = rt.step_complete(run_id, "interim")
    sub_exec_id = _exec_id_from(d2)

    # Subroutine calls need
    rt.need(sub_exec_id, "I need more context")

    # Main thread relays
    d3 = rt.step_complete(run_id, "need: I need more context")

    # v1: subroutine need fails the run
    assert d3["action"] == "failed"
    assert "need" in d3["error"].lower() or "I need more context" in d3["error"]
