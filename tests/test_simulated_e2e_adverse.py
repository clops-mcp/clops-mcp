"""Adverse-path simulated E2E tests.

Same Layer 2.5 wiring as test_simulated_e2e.py — full stack of MCP
handlers + Runtime + hook decide(), no LLM, no Claude Code — but
exercising failure paths and architectural invariants under stress.

Each test documents a contract: what the system promises when a
subagent (or the harness) misbehaves.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

import pytest

from clops import Concept, Op, Tool, sequence
from clops.runtime.hook_server import decide
from clops.runtime.mcp_server import FlowServer, ServerConfig


# ---- Fixtures --------------------------------------------------------


class M(Concept):
    description = "a message"


class R(Concept):
    description = "a result"


@pytest.fixture
def srv():
    """A server with two entry Ops (Solo and Pipeline) and one tool."""

    def _flaky(value: str = "ok"):
        if value == "boom":
            raise RuntimeError("tool handler exploded")
        return {"value": value}

    flaky = Tool(name="flaky", description="May raise.", parameters={"value": str}, handler=_flaky)

    class StepA(Op):
        Input = M
        Output = R
        Intent = "Step A."
        Meta = "Test fixture Op for validating adverse E2E scenarios."
        Tools = [flaky]

    class StepB(Op):
        Input = R
        Output = R
        Intent = "Step B."
        Meta = "Test fixture Op for validating adverse E2E scenarios."

    class Solo(Op):
        Input = M
        Output = R
        Intent = "Just one step."
        Meta = "Test fixture Op for validating adverse E2E scenarios."
        Tools = [flaky]
        entry = True

    class Pipeline(Op):
        Input = M
        Output = R
        Intent = "A then B."
        Meta = "Test fixture Op for validating adverse E2E scenarios."
        body = sequence(StepA, StepB)
        entry = True

    server = FlowServer(ServerConfig())
    return server


_EXEC_RE = re.compile(r'execution_id="(exec_[a-f0-9]+)"')


def _exec_id_from(dispatch: dict) -> str:
    m = _EXEC_RE.search(dispatch["agent_config"]["prompt"])
    assert m, "prompt missing execution_id literal"
    return m.group(1)


def _decode(text_content_list) -> dict:
    return json.loads(text_content_list[0].text)


# ---- 1. Per-session hook-queue isolation ----------------------------


def test_two_parent_sessions_keep_isolated_hook_queues(srv):
    """Two simultaneous runs from two parent sessions must not cross-release.

    Architecturally critical for the teams-and-parallel future: a
    subagent stop in session A must never release a completion queued
    by a subagent in session B.
    """
    d1 = srv._handle_start_process({"process": "Solo", "input": "from-a"})
    d2 = srv._handle_start_process({"process": "Solo", "input": "from-b"})
    exec1 = _exec_id_from(d1)
    exec2 = _exec_id_from(d2)

    # Both subagents complete, each with their own parent_session_id.
    srv._handle_complete({"execution_id": exec1, "output": "out-a", "_parent_session_id": "sess-A"})
    srv._handle_complete({"execution_id": exec2, "output": "out-b", "_parent_session_id": "sess-B"})

    # Hook fires for sess-A: must release exec1, not exec2.
    assert decide(srv.runtime, {"session_id": "sess-A"}) == {}
    # Hook fires for sess-A again: queue empty, must block (not steal sess-B's).
    blocked = decide(srv.runtime, {"session_id": "sess-A"})
    assert blocked["decision"] == "block"
    # sess-B's queue is still intact.
    assert decide(srv.runtime, {"session_id": "sess-B"}) == {}


# ---- 2. Composition halts cleanly on need ---------------------------


def test_need_in_first_leaf_halts_pipeline_without_dispatching_second(srv):
    """Phase 2 slice 04: a need in the first leaf surfaces as needs_resolution.
    If the main thread aborts, the run halts without dispatching downstream."""
    d1 = srv._handle_start_process({"process": "Pipeline", "input": "ambiguous"})
    exec1 = _exec_id_from(d1)
    assert d1["agent_config"]["description"].startswith("Execute StepA")

    srv._handle_need({"execution_id": exec1, "reason": "no customer_id", "_parent_session_id": "sess"})
    result = srv._handle_step_complete({"run_id": d1["run_id"], "result": None})

    assert result["action"] == "needs_resolution"
    assert "no customer_id" in result["reason"]

    # Main chooses to abort rather than resolve.
    srv._handle_abort_run({"run_id": d1["run_id"]})

    status = srv._handle_run_status({"run_id": d1["run_id"]})
    assert status["status"] == "aborted"
    op_names = [e["op_name"] for e in status["executions"]]
    # Critically: StepB was never dispatched.
    assert op_names == ["StepA"]
    assert "StepB" not in op_names


# ---- 3. Op tool handler raises --------------------------------------


def test_call_tool_handler_exception_surfaces_as_structured_error_not_crash(srv):
    d = srv._handle_start_process({"process": "Solo", "input": "hi"})
    exec_id = _exec_id_from(d)

    # Drive call_tool through _dispatch_tool_call so we observe the
    # structured response (not a raised exception).
    response = srv._dispatch_tool_call(
        "call_tool",
        {"execution_id": exec_id, "name": "flaky", "arguments": {"value": "boom"}},
    )
    payload = _decode(response)
    assert "error" in payload
    assert "tool handler exploded" in payload["error"]

    # The run must still be progressable: the subagent can recover
    # by calling the tool with valid args, then complete.
    response2 = srv._dispatch_tool_call(
        "call_tool",
        {"execution_id": exec_id, "name": "flaky", "arguments": {"value": "ok"}},
    )
    assert _decode(response2) == {"value": "ok"}

    srv._handle_complete({"execution_id": exec_id, "output": "done"})
    done = srv._handle_step_complete({"run_id": d["run_id"], "result": "done"})
    assert done["action"] == "done"


# ---- 4. complete with wrong execution_id ----------------------------


def test_complete_with_wrong_execution_id_does_not_corrupt_state(srv):
    d = srv._handle_start_process({"process": "Solo", "input": "hi"})
    real_exec = _exec_id_from(d)

    # Subagent (buggy or malicious) calls with a fabricated id.
    response = srv._dispatch_tool_call(
        "complete",
        {"execution_id": "exec_does_not_exist", "output": "stale"},
    )
    payload = _decode(response)
    assert "error" in payload
    assert "not found" in payload["error"]

    # The real execution is untouched.
    real = srv.runtime.get_run(d["run_id"]).get_execution(real_exec)
    assert real.status.value == "running"
    assert real.completed_flag is False
    assert real.output_snapshot is None

    # Subagent recovers by calling with the right id.
    srv._handle_complete({"execution_id": real_exec, "output": "real"})
    done = srv._handle_step_complete({"run_id": d["run_id"], "result": "real"})
    assert done["action"] == "done"
    assert done["output"] == "real"


# ---- 5. Double complete ---------------------------------------------


def test_second_complete_on_same_execution_is_rejected_first_one_wins(srv):
    d = srv._handle_start_process({"process": "Solo", "input": "hi"})
    exec_id = _exec_id_from(d)

    srv._handle_complete({"execution_id": exec_id, "output": "first"})
    response = srv._dispatch_tool_call(
        "complete",
        {"execution_id": exec_id, "output": "second"},
    )
    payload = _decode(response)
    assert "error" in payload
    assert "already terminal" in payload["error"]

    # First output is preserved.
    done = srv._handle_step_complete({"run_id": d["run_id"], "result": "first"})
    assert done["output"] == "first"


# ---- 6. abort_run + late subagent call ------------------------------


def test_abort_then_late_subagent_call_documents_contract(srv):
    """After abort, all non-terminal executions are marked FAILED (for
    subroutine cancellation propagation). A late complete() from a stale
    subagent is refused because the execution is already terminal.

    Previously complete() succeeded here (the execution wasn't marked
    terminal on abort). Tightened in subroutine-ops-v1 so abort
    propagates cancellation to suspended/running/pending executions.
    """
    d = srv._handle_start_process({"process": "Solo", "input": "hi"})
    exec_id = _exec_id_from(d)

    aborted = srv._handle_abort_run({"run_id": d["run_id"]})
    assert aborted["status"] == "aborted"

    # Execution was marked FAILED by abort's cancellation propagation.
    execution = srv.runtime.get_run(d["run_id"]).get_execution(exec_id)
    assert execution.status.value == "failed"
    assert execution.error == "Run aborted"

    # Late subagent call: refused because execution is already terminal.
    response = srv._dispatch_tool_call(
        "complete",
        {"execution_id": exec_id, "output": "too late"},
    )
    payload = _decode(response)
    assert "error" in payload
    assert "already terminal" in payload["error"]


# ---- 7. Library import failure E2E narrative -----------------------


def test_library_import_failure_surfaces_through_full_dispatch_path():
    bad = FlowServer(ServerConfig(libraries=["totally.fake.package.xyz"]))
    bad.load_library_safe()

    # Main thread tries to list processes — gets a structured error.
    response = bad._dispatch_tool_call("list_processes", {})
    payload = _decode(response)
    assert "error" in payload
    assert "totally.fake.package.xyz" in payload["error"]

    # Same on start_process: doesn't proceed.
    response2 = bad._dispatch_tool_call(
        "start_process",
        {"process": "Whatever", "input": "x"},
    )
    payload2 = _decode(response2)
    assert "error" in payload2
    assert "totally.fake.package.xyz" in payload2["error"]


# ---- 8. start_process for unknown name ------------------------------


def test_start_process_for_unknown_op_returns_structured_error(srv):
    response = srv._dispatch_tool_call(
        "start_process",
        {"process": "GhostOp", "input": "x"},
    )
    payload = _decode(response)
    assert "error" in payload
    assert "Unknown process" in payload["error"]


# ---- 9. start_process for non-entry Op -------------------------------


def test_start_process_for_non_entry_op_blocked_at_mcp_boundary(srv):
    # StepA exists in the registry (it's part of Pipeline) but is
    # not entry-tagged. Direct invocation must be blocked.
    response = srv._dispatch_tool_call(
        "start_process",
        {"process": "StepA", "input": "x"},
    )
    payload = _decode(response)
    assert "error" in payload
    assert "not an entry point" in payload["error"]

    # And it's not in the catalog either.
    catalog = srv._build_tool_catalog()
    assert "StepA" not in {t.name for t in catalog}


# ---- 10. Hook fires for unknown session -----------------------------


def test_hook_for_unknown_session_fails_open(srv):
    # No runs at all; hook fires for a session we've never heard of.
    # Must allow termination (we have no grounds to block).
    assert decide(srv.runtime, {"session_id": "unknown-session"}) == {}


# ---- 11. call_tool against terminal execution ----------------------


def test_branch_on_unknown_key_surfaces_failure_through_step_complete():
    """Adverse: branch's key returns a value not in arms. Run fails with
    structured error; the unmatched arm is never dispatched."""
    from clops import Op, sequence, branch_on

    class Mx(Concept):
        description = "m"

    class Rx(Concept):
        description = "r"

    class Up(Op):
        Input = Mx
        Output = Rx
        Intent = "u"
        Meta = "Test fixture Op for validating adverse branch_on unknown key."

    class Arm(Op):
        Input = Rx
        Output = Rx
        Intent = "a"
        Meta = "Test fixture Op for validating adverse branch_on unknown key."

    class Bad(Op):
        Input = Mx
        Output = Rx
        Intent = "P."
        Meta = "Test fixture Op for validating adverse branch_on unknown key."
        body = sequence(Up, branch_on(key=lambda _: "ghost", arms={"a": Arm}))
        entry = True

    server = FlowServer(ServerConfig())
    d = server._handle_start_process({"process": "Bad", "input": "x"})
    exec1 = _exec_id_from(d)
    server._handle_complete({"execution_id": exec1, "output": "anything", "_parent_session_id": "p"})
    result = server._handle_step_complete({"run_id": d["run_id"], "result": "anything"})

    assert result["action"] == "failed"
    assert "No arm" in result["error"]
    assert "'ghost'" in result["error"]

    # Arm was never dispatched.
    op_names = sorted(e.op_name for e in server.runtime.get_run(d["run_id"]).executions.values())
    assert op_names == ["Up"]


def test_branch_on_key_function_exception_surfaces_failure():
    """Adverse: key function raises. Run fails with the exception in the error."""
    from clops import Op, sequence, branch_on

    class Mx(Concept):
        description = "m"

    class Rx(Concept):
        description = "r"

    class Up(Op):
        Input = Mx
        Output = Rx
        Intent = "u"
        Meta = "Test fixture Op for validating adverse branch key exception."

    class Arm(Op):
        Input = Rx
        Output = Rx
        Intent = "a"
        Meta = "Test fixture Op for validating adverse branch key exception."

    class Boom(Op):
        Input = Mx
        Output = Rx
        Intent = "P."
        Meta = "Test fixture Op for validating adverse branch key exception."
        body = sequence(Up, branch_on(
            key=lambda _: (_ for _ in ()).throw(ValueError("explode")),
            arms={"a": Arm},
        ))
        entry = True

    server = FlowServer(ServerConfig())
    d = server._handle_start_process({"process": "Boom", "input": "x"})
    exec1 = _exec_id_from(d)
    server._handle_complete({"execution_id": exec1, "output": "x", "_parent_session_id": "p"})
    result = server._handle_step_complete({"run_id": d["run_id"], "result": "x"})

    assert result["action"] == "failed"
    assert "explode" in result["error"]


def test_loop_max_iterations_exhaustion_surfaces_failure():
    """Adverse: predicate never returns truthy; loop fails after max_iterations."""
    from clops import Op, sequence, loop

    class Mx(Concept):
        description = "m"

    class Rx(Concept):
        description = "r"

    class Seed(Op):
        Input = Mx
        Output = Rx
        Intent = "s"
        Meta = "Test fixture Op for validating adverse loop max_iterations."

    class Step(Op):
        Input = Rx
        Output = Rx
        Intent = "step"
        Meta = "Test fixture Op for validating adverse loop max_iterations."

    class P(Op):
        Input = Mx
        Output = Rx
        Intent = "P."
        Meta = "Test fixture Op for validating adverse loop max_iterations."
        body = sequence(Seed, loop(body=Step, until=lambda _: False, max_iterations=2))
        entry = True

    server = FlowServer(ServerConfig())
    d = server._handle_start_process({"process": "P", "input": "x"})
    run_id = d["run_id"]
    exec_seed = _exec_id_from(d)
    server._handle_complete({"execution_id": exec_seed, "output": "seed", "_parent_session_id": "p"})
    d = server._handle_step_complete({"run_id": run_id, "result": "seed"})

    # First iteration
    exec1 = _exec_id_from(d)
    server._handle_complete({"execution_id": exec1, "output": "v0", "_parent_session_id": "p"})
    d = server._handle_step_complete({"run_id": run_id, "result": "v0"})

    # Second iteration
    exec2 = _exec_id_from(d)
    server._handle_complete({"execution_id": exec2, "output": "v1", "_parent_session_id": "p"})
    result = server._handle_step_complete({"run_id": run_id, "result": "v1"})

    assert result["action"] == "failed"
    assert "max_iterations" in result["error"]
    assert "(2)" in result["error"]


def test_loop_until_predicate_raises_surfaces_failure():
    from clops import Op, sequence, loop

    class Mx(Concept):
        description = "m"

    class Rx(Concept):
        description = "r"

    class Seed(Op):
        Input = Mx
        Output = Rx
        Intent = "s"
        Meta = "Test fixture Op for validating adverse loop predicate raise."

    class Step(Op):
        Input = Rx
        Output = Rx
        Intent = "step"
        Meta = "Test fixture Op for validating adverse loop predicate raise."

    class P(Op):
        Input = Mx
        Output = Rx
        Intent = "P."
        Meta = "Test fixture Op for validating adverse loop predicate raise."
        body = sequence(
            Seed,
            loop(
                body=Step,
                until=lambda _: (_ for _ in ()).throw(RuntimeError("predicate explode")),
            ),
        )
        entry = True

    server = FlowServer(ServerConfig())
    d = server._handle_start_process({"process": "P", "input": "x"})
    run_id = d["run_id"]
    exec_seed = _exec_id_from(d)
    server._handle_complete({"execution_id": exec_seed, "output": "seed", "_parent_session_id": "p"})
    d = server._handle_step_complete({"run_id": run_id, "result": "seed"})

    exec1 = _exec_id_from(d)
    server._handle_complete({"execution_id": exec1, "output": "v0", "_parent_session_id": "p"})
    result = server._handle_step_complete({"run_id": run_id, "result": "v0"})

    assert result["action"] == "failed"
    assert "predicate explode" in result["error"]


def test_gather_branch_failure_propagates_to_run_failure():
    """Adverse: one branch in a gather calls need. Gather fails the run."""
    from clops import Op, sequence, gather

    class Mx(Concept):
        description = "m"

    class Rx(Concept):
        description = "r"

    class Seed(Op):
        Input = Mx
        Output = Rx
        Intent = "s"
        Meta = "Test fixture Op for validating adverse gather branch failure."

    class A(Op):
        Input = Rx
        Output = Rx
        Intent = "a"
        Meta = "Test fixture Op for validating adverse gather branch failure."

    class B(Op):
        Input = Rx
        Output = Rx
        Intent = "b"
        Meta = "Test fixture Op for validating adverse gather branch failure."

    class P(Op):
        Input = Mx
        Output = Rx
        Intent = "P."
        Meta = "Test fixture Op for validating adverse gather branch failure."
        body = sequence(Seed, gather(A, B))
        entry = True

    server = FlowServer(ServerConfig())
    d = server._handle_start_process({"process": "P", "input": "x"})
    run_id = d["run_id"]
    exec_seed = _exec_id_from(d)
    server._handle_complete({"execution_id": exec_seed, "output": "seed", "_parent_session_id": "p"})
    parallel = server._handle_step_complete({"run_id": run_id, "result": "seed"})
    ids = parallel["execution_ids"]

    # A completes; B calls need.
    server._handle_complete({"execution_id": ids[0], "output": "a-out", "_parent_session_id": "p"})
    server._handle_need({"execution_id": ids[1], "reason": "b-missing-info", "_parent_session_id": "p"})

    result = server._handle_step_complete_parallel(
        {"run_id": run_id, "results": {ids[0]: "a-out", ids[1]: None}}
    )
    assert result["action"] == "failed"
    assert "b-missing-info" in result["error"]


def test_gather_step_complete_parallel_missing_ids_returns_structured_error():
    from clops import Op, sequence, gather

    class Mx(Concept):
        description = "m"

    class Rx(Concept):
        description = "r"

    class Seed(Op):
        Input = Mx
        Output = Rx
        Intent = "s"
        Meta = "Test fixture Op for validating adverse gather missing ids."

    class A(Op):
        Input = Rx
        Output = Rx
        Intent = "a"
        Meta = "Test fixture Op for validating adverse gather missing ids."

    class B(Op):
        Input = Rx
        Output = Rx
        Intent = "b"
        Meta = "Test fixture Op for validating adverse gather missing ids."

    class P(Op):
        Input = Mx
        Output = Rx
        Intent = "P."
        Meta = "Test fixture Op for validating adverse gather missing ids."
        body = sequence(Seed, gather(A, B))
        entry = True

    server = FlowServer(ServerConfig())
    d = server._handle_start_process({"process": "P", "input": "x"})
    run_id = d["run_id"]
    exec_seed = _exec_id_from(d)
    server._handle_complete({"execution_id": exec_seed, "output": "seed", "_parent_session_id": "p"})
    parallel = server._handle_step_complete({"run_id": run_id, "result": "seed"})
    ids = parallel["execution_ids"]

    # Pass only one of the two expected ids.
    response = server._dispatch_tool_call(
        "step_complete_parallel",
        {"run_id": run_id, "results": {ids[0]: "a-out"}},
    )
    payload = _decode(response)
    assert "error" in payload
    assert "missing execution_ids" in payload["error"]


def test_need_persists_after_resolution_fails_the_run():
    """Adverse: subagent calls need again after resolve_need. Run fails
    loudly — this protects against infinite resolve loops."""
    from clops import Op

    class Mx(Concept):
        description = "m"

    class Rx(Concept):
        description = "r"

    class Stubborn(Op):
        Input = Mx
        Output = Rx
        Intent = "Always need."
        Meta = "Test fixture Op for validating adverse persistent need."
        entry = True

    server = FlowServer(ServerConfig())
    d = server._handle_start_process({"process": "Stubborn", "input": "x"})
    run_id = d["run_id"]
    exec_id = next(iter(server.runtime.get_run(run_id).pending_executions))

    # First need
    server._handle_need({"execution_id": exec_id, "reason": "v1", "_parent_session_id": "p"})
    result = server._handle_step_complete({"run_id": run_id, "result": None})
    assert result["action"] == "needs_resolution"

    # Resolve
    server._handle_resolve_need({
        "run_id": run_id, "execution_id": exec_id, "supplemental_input": "here"
    })

    # Subagent needs again
    server._handle_need({"execution_id": exec_id, "reason": "v2-persisted", "_parent_session_id": "p"})
    failed = server._handle_step_complete({"run_id": run_id, "result": None})
    assert failed["action"] == "failed"
    assert "persisted after resolution" in failed["error"]
    assert "v2-persisted" in failed["error"]


def test_resolve_need_on_wrong_execution_returns_structured_error():
    from clops import Op

    class Mx(Concept):
        description = "m"

    class Rx(Concept):
        description = "r"

    class A(Op):
        Input = Mx
        Output = Rx
        Intent = "a"
        Meta = "Test fixture Op for validating adverse resolve_need wrong exec."
        entry = True

    server = FlowServer(ServerConfig())
    d = server._handle_start_process({"process": "A", "input": "x"})
    run_id = d["run_id"]

    # Try to resolve a need on an execution that hasn't needed anything.
    response = server._dispatch_tool_call(
        "resolve_need",
        {"run_id": run_id, "execution_id": "exec_ghost", "supplemental_input": "x"},
    )
    payload = _decode(response)
    assert "error" in payload
    assert "not found" in payload["error"]


def test_call_tool_after_complete_still_works_documents_contract(srv):
    """Documenting: call_tool currently does not check execution
    terminal status. It simply routes if the tool is declared and the
    execution exists. This is a minor leak (a misbehaving subagent
    could keep calling tools after marking itself complete); harmless
    in practice but worth a backlog item if it ever bites.
    """
    d = srv._handle_start_process({"process": "Solo", "input": "hi"})
    exec_id = _exec_id_from(d)
    srv._handle_complete({"execution_id": exec_id, "output": "done"})

    # Subagent (misbehaving) calls call_tool after complete.
    response = srv._dispatch_tool_call(
        "call_tool",
        {"execution_id": exec_id, "name": "flaky", "arguments": {"value": "x"}},
    )
    # Currently: succeeds and returns the handler value.
    assert _decode(response) == {"value": "x"}
    # If we tighten this, replace with: assert "error" in payload.
