"""Protocol tests: drive the runtime directly with mock subagent personas.

Under Phase 1b, subagents receive their execution_id via their rendered
prompt and pass it explicitly on every complete/need call. The SubagentStop
hook is modeled as calls to `release_one_completed(parent_session_id)`.
"""

import pytest

from clops import Concept, Op, branch_on, loop, sequence
from clops.runtime import ExecutionStatus, Runtime, RunStatus
from clops.runtime.core import RuntimeError_


def _holds(dispatch: dict) -> bool:
    """True if the dispatch prompt uses the manifest (hold-checklist) contract."""
    return "## What to hold by the end" in dispatch["agent_config"]["prompt"]


def _full(dispatch: dict) -> bool:
    """True if the dispatch prompt uses the full-output contract."""
    return "## What you'll produce" in dispatch["agent_config"]["prompt"]


class M(Concept):
    description = "a message"


class R(Concept):
    description = "a result"


@pytest.fixture
def library():
    """Register a small library: leaf A, leaf B, and Pipe(A, B)."""

    class OpA(Op):
        Input = M
        Output = R
        Intent = "Emit A."
        Meta = "Test fixture Op for validating runtime core."

    class OpB(Op):
        Input = R
        Output = R
        Intent = "Emit B."
        Meta = "Test fixture Op for validating runtime core."

    class Pipe(Op):
        Input = M
        Output = R
        Intent = "Chain A then B."
        Meta = "Test fixture Op for validating sequential composition."
        body = sequence(OpA, OpB)

    return OpA, OpB, Pipe


# ---- Mock subagent personas ------------------------------------------


def persona_complete(runtime: Runtime, execution_id: str, output, *, parent="sess-main"):
    runtime.complete(execution_id, output, parent_session_id=parent)


def persona_need(runtime: Runtime, execution_id: str, reason: str, *, parent="sess-main"):
    runtime.need(execution_id, reason, parent_session_id=parent)


def _execution_id_from_dispatch(dispatch: dict) -> str:
    return dispatch["agent_config"]["_metadata"]["execution_id"] if "_metadata" in dispatch["agent_config"] else _embedded_id(dispatch)


def _embedded_id(dispatch: dict) -> str:
    # In the public dispatch instruction the _metadata block is stripped.
    # The execution_id is embedded in the prompt text; tests grab it from
    # the runtime's state instead.
    raise AssertionError("tests should read execution_id from runtime state, not the public dispatch")


def _pending_id(runtime: Runtime, run_id: str) -> str:
    pending = runtime.get_run(run_id).pending_executions
    assert len(pending) == 1, f"expected exactly one pending execution, got {pending}"
    return next(iter(pending))


# ---- Happy paths ------------------------------------------------------


def test_leaf_run_end_to_end(library):
    OpA, *_ = library
    rt = Runtime()

    dispatch = rt.start("OpA", "hello")
    assert dispatch["action"] == "dispatch"
    assert dispatch["agent_template"] == "clops-executor"
    assert dispatch["report_via"] == "step_complete"
    assert "_metadata" not in dispatch["agent_config"]
    run_id = dispatch["run_id"]

    exec_id = _pending_id(rt, run_id)
    persona_complete(rt, exec_id, "A-result")

    result = rt.step_complete(run_id, "A-result")
    assert result["action"] == "done"
    assert result["output"] == "A-result"

    status = rt.status(run_id)
    assert status["status"] == RunStatus.COMPLETED.value
    assert status["executions"][0]["status"] == ExecutionStatus.COMPLETED.value
    assert status["pending_executions"] == []


def test_sequential_composition_dispatches_each_leaf(library):
    OpA, OpB, Pipe = library
    rt = Runtime()

    d1 = rt.start("Pipe", {"content": "hi"})
    assert d1["action"] == "dispatch"
    assert d1["agent_config"]["description"].startswith("Execute OpA")
    run_id = d1["run_id"]

    persona_complete(rt, _pending_id(rt, run_id), "A-out")
    d2 = rt.step_complete(run_id, "A-out")
    assert d2["action"] == "dispatch"
    assert d2["agent_config"]["description"].startswith("Execute OpB")

    persona_complete(rt, _pending_id(rt, run_id), "B-out")
    done = rt.step_complete(run_id, "B-out")
    assert done["action"] == "done"
    assert done["output"] == "B-out"


def test_input_to_second_leaf_is_first_leafs_output(library):
    _, _, Pipe = library
    rt = Runtime()

    d1 = rt.start("Pipe", {"content": "hi"})
    run_id = d1["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), {"classified": "billing"})
    d2 = rt.step_complete(run_id, {"classified": "billing"})

    assert d2["action"] == "dispatch"
    # OpB's prompt should include OpA's output under "Your input"
    assert "billing" in d2["agent_config"]["prompt"]


# ---- Execution_id correlation ----------------------------------------


def test_prompt_embeds_execution_id(library):
    OpA, *_ = library
    rt = Runtime()
    dispatch = rt.start("OpA", "hi")
    run_id = dispatch["run_id"]
    exec_id = _pending_id(rt, run_id)
    assert exec_id in dispatch["agent_config"]["prompt"]


def test_complete_requires_execution_id(library):
    OpA, *_ = library
    rt = Runtime()
    rt.start("OpA", "hi")
    with pytest.raises(RuntimeError_):
        rt.complete("", "x")


def test_complete_with_unknown_execution_id_raises(library):
    OpA, *_ = library
    rt = Runtime()
    rt.start("OpA", "hi")
    with pytest.raises(RuntimeError_):
        rt.complete("exec_bogus", "x")


def test_complete_on_already_terminal_execution_raises(library):
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "hi")
    exec_id = _pending_id(rt, d["run_id"])
    rt.complete(exec_id, "first")
    with pytest.raises(RuntimeError_):
        rt.complete(exec_id, "second")


# ---- SubagentStop hook surface ---------------------------------------


def test_release_one_completed_returns_queued_execution(library):
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "hi")
    exec_id = _pending_id(rt, d["run_id"])
    rt.complete(exec_id, "done", parent_session_id="parent-1")

    released = rt.release_one_completed("parent-1")
    assert released == exec_id
    # Queue empty now
    assert rt.release_one_completed("parent-1") is None


def test_release_without_queue_returns_none():
    rt = Runtime()
    assert rt.release_one_completed("unknown-session") is None


def test_need_also_queues_for_hook_release(library):
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "bad")
    exec_id = _pending_id(rt, d["run_id"])
    rt.need(exec_id, "missing data", parent_session_id="parent-1")
    assert rt.release_one_completed("parent-1") == exec_id


def test_release_queue_is_fifo(library):
    OpA, OpB, Pipe = library
    rt = Runtime()
    # First dispatch
    d1 = rt.start("Pipe", "x")
    exec_a = _pending_id(rt, d1["run_id"])
    rt.complete(exec_a, "A-out", parent_session_id="parent-1")
    rt.step_complete(d1["run_id"], "A-out")

    # Second dispatch (same parent session)
    exec_b = _pending_id(rt, d1["run_id"])
    rt.complete(exec_b, "B-out", parent_session_id="parent-1")

    # FIFO order
    assert rt.release_one_completed("parent-1") == exec_a
    assert rt.release_one_completed("parent-1") == exec_b


# ---- Need / error paths ----------------------------------------------


def test_need_surfaces_needs_resolution_action(library):
    """Phase 2 slice 04: need() no longer fails the run; it routes to main
    thread with a needs_resolution payload."""
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "bad")
    run_id = d["run_id"]
    exec_id = _pending_id(rt, run_id)

    persona_need(rt, exec_id, "missing customer_id")

    result = rt.step_complete(run_id, None)
    assert result["action"] == "needs_resolution"
    assert result["reason"] == "missing customer_id"
    assert result["execution_id"] == exec_id
    assert result["op_name"] == "OpA"
    assert result["resolve_via"] == "resolve_need"
    # Run is still running (suspended, awaiting resolution).
    assert rt.status(run_id)["status"] == RunStatus.RUNNING.value


def test_abort_after_need_leaves_run_aborted(library):
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "bad")
    run_id = d["run_id"]
    exec_id = _pending_id(rt, run_id)
    persona_need(rt, exec_id, "missing x")
    rt.step_complete(run_id, None)  # → needs_resolution
    rt.abort(run_id)
    assert rt.status(run_id)["status"] == RunStatus.ABORTED.value


# ---- need resolution ------------------------------------------------


def test_resolve_need_redispatches_with_supplemental(library):
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "bad")
    run_id = d["run_id"]
    exec_id = _pending_id(rt, run_id)
    persona_need(rt, exec_id, "missing customer_id")
    rt.step_complete(run_id, None)  # → needs_resolution

    redispatch = rt.resolve_need(run_id, exec_id, {"customer_id": "cust_42"})
    assert redispatch["action"] == "dispatch"
    # Same execution_id — re-dispatch, not new execution.
    new_exec_id = _pending_id(rt, run_id)
    assert new_exec_id == exec_id
    # Supplemental section surfaces in the prompt.
    prompt = redispatch["agent_config"]["prompt"]
    assert "Supplemental input" in prompt
    assert "cust_42" in prompt
    # Attempts incremented.
    execution = rt.get_run(run_id).get_execution(exec_id)
    assert execution.attempts == 2
    assert execution.need_resolved is True


def test_resolved_need_can_then_complete_normally(library):
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "bad")
    run_id = d["run_id"]
    exec_id = _pending_id(rt, run_id)
    persona_need(rt, exec_id, "missing customer_id")
    rt.step_complete(run_id, None)
    rt.resolve_need(run_id, exec_id, "here is the info")
    # Re-dispatched subagent completes normally.
    persona_complete(rt, exec_id, "done")
    done = rt.step_complete(run_id, "done")
    assert done["action"] == "done"
    assert done["output"] == "done"


def test_second_need_after_resolve_fails_run_persistently(library):
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "bad")
    run_id = d["run_id"]
    exec_id = _pending_id(rt, run_id)
    persona_need(rt, exec_id, "need-v1")
    rt.step_complete(run_id, None)
    rt.resolve_need(run_id, exec_id, "supplemental")
    # Subagent needs again after resolution.
    persona_need(rt, exec_id, "need-v2")
    result = rt.step_complete(run_id, None)
    assert result["action"] == "failed"
    assert "persisted after resolution" in result["error"]
    assert "need-v2" in result["error"]


def test_resolve_need_on_unknown_execution_raises(library):
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "x")
    with pytest.raises(RuntimeError_, match="not found"):
        rt.resolve_need(d["run_id"], "exec_ghost", "info")


def test_resolve_need_on_non_need_execution_raises(library):
    """Calling resolve_need on an execution that isn't awaiting resolution."""
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "x")
    exec_id = _pending_id(rt, d["run_id"])
    with pytest.raises(RuntimeError_, match="not awaiting need resolution"):
        rt.resolve_need(d["run_id"], exec_id, "info")


def test_resolve_need_on_terminal_run_raises(library):
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "x")
    exec_id = _pending_id(rt, d["run_id"])
    persona_need(rt, exec_id, "missing x")
    rt.step_complete(d["run_id"], None)  # needs_resolution
    rt.abort(d["run_id"])
    with pytest.raises(RuntimeError_, match="not running"):
        rt.resolve_need(d["run_id"], exec_id, "info")


def test_has_completed_flag_reflects_state(library):
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "hi")
    exec_id = _pending_id(rt, d["run_id"])
    assert rt.has_completed(exec_id) is False
    rt.complete(exec_id, "done")
    assert rt.has_completed(exec_id) is True


def test_has_completed_unknown_execution_is_false():
    rt = Runtime()
    assert rt.has_completed("unknown") is False


# ---- Status / list ---------------------------------------------------


def test_list_processes_only_surfaces_entry_tagged_ops(library):
    OpA, OpB, Pipe = library
    Pipe.entry = True
    try:
        rt = Runtime()
        names = [p["name"] for p in rt.list_processes()]
        assert names == ["Pipe"]
    finally:
        Pipe.entry = False


def test_list_processes_empty_when_nothing_tagged(library):
    rt = Runtime()
    assert rt.list_processes() == []


def test_start_enforce_entry_blocks_non_entry_op(library):
    OpA, *_ = library
    rt = Runtime()
    with pytest.raises(RuntimeError_, match="not an entry point"):
        rt.start("OpA", "hi", enforce_entry=True)


def test_start_enforce_entry_allows_entry_op(library):
    OpA, OpB, Pipe = library
    Pipe.entry = True
    try:
        rt = Runtime()
        d = rt.start("Pipe", "hi", enforce_entry=True)
        assert d["action"] == "dispatch"
    finally:
        Pipe.entry = False


def test_abort_marks_run_aborted(library):
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "hi")
    result = rt.abort(d["run_id"])
    assert result["status"] == RunStatus.ABORTED.value


def test_step_complete_errors_when_no_pending(library):
    OpA, *_ = library
    rt = Runtime()
    d = rt.start("OpA", "hi")
    exec_id = _pending_id(rt, d["run_id"])
    rt.complete(exec_id, "done")
    rt.step_complete(d["run_id"], "done")
    # Run is now terminal; step_complete again should error
    with pytest.raises(RuntimeError_):
        rt.step_complete(d["run_id"], "more")


# ---- branch_on execution --------------------------------------------


@pytest.fixture
def branch_library():
    """Triage that returns prose containing a category, branch routes
    to one of three handlers based on a key function."""
    from clops import branch_on

    class Triage(Op):
        Input = M
        Output = R
        Intent = "Categorize."
        Meta = "Test fixture Op for validating branch_on routing."

    class Billing(Op):
        Input = R
        Output = R
        Intent = "Handle billing."
        Meta = "Test fixture Op for validating branch_on routing."

    class Tech(Op):
        Input = R
        Output = R
        Intent = "Handle technical."
        Meta = "Test fixture Op for validating branch_on routing."

    class General(Op):
        Input = R
        Output = R
        Intent = "Handle general."
        Meta = "Test fixture Op for validating branch_on routing."

    def _key(triage_output):
        text = str(triage_output).lower()
        if "billing" in text:
            return "billing"
        if "tech" in text:
            return "technical"
        return "general"

    class Route(Op):
        Input = M
        Output = R
        Intent = "Triage then route."
        Meta = "Test fixture Op for validating branch_on composition."
        body = sequence(
            Triage,
            branch_on(key=_key, arms={"billing": Billing, "technical": Tech, "general": General}),
        )

    return Triage, Billing, Tech, General, Route


def test_branch_on_routes_to_matched_arm_only(branch_library):
    Triage, Billing, Tech, General, Route = branch_library
    rt = Runtime()
    d = rt.start("Route", "double charge problem")
    run_id = d["run_id"]

    # First leaf: Triage. Subagent emits "billing".
    persona_complete(rt, _pending_id(rt, run_id), "billing")
    d2 = rt.step_complete(run_id, "billing")

    # Branch resolves; the matched arm (Billing) is dispatched, not the others.
    assert d2["action"] == "dispatch"
    assert d2["agent_config"]["description"].startswith("Execute Billing")

    persona_complete(rt, _pending_id(rt, run_id), "refund issued")
    done = rt.step_complete(run_id, "refund issued")
    assert done["action"] == "done"
    assert done["output"] == "refund issued"

    # State graph: only Triage and Billing executed; Tech and General never dispatched.
    op_names = [e.op_name for e in rt.get_run(run_id).executions.values()]
    assert sorted(op_names) == ["Billing", "Triage"]


def test_branch_on_unknown_key_fails_run_with_structured_error():
    """Key function returns a value the branch_on doesn't have an arm for."""
    from clops import branch_on

    class Up(Op):
        Input = M
        Output = R
        Intent = "Up."
        Meta = "Test fixture Op for validating unknown branch key."

    class A(Op):
        Input = R
        Output = R
        Intent = "A."
        Meta = "Test fixture Op for validating unknown branch key."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating unknown branch key."
        body = sequence(
            Up,
            branch_on(key=lambda _: "ghost", arms={"a": A}),
        )

    rt = Runtime()
    d = rt.start("P", "x")
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "anything")
    result = rt.step_complete(run_id, "anything")
    assert result["action"] == "failed"
    assert "No arm" in result["error"]
    assert "'ghost'" in result["error"]


def test_branch_on_key_function_exception_fails_run():
    from clops import branch_on

    def _bad_key(_):
        raise ValueError("boom")

    class Up(Op):
        Input = M
        Output = R
        Intent = "Up."
        Meta = "Test fixture Op for validating branch key exception."

    class A(Op):
        Input = R
        Output = R
        Intent = "A."
        Meta = "Test fixture Op for validating branch key exception."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating branch key exception."
        body = sequence(Up, branch_on(key=_bad_key, arms={"a": A}))

    rt = Runtime()
    d = rt.start("P", "x")
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "anything")
    result = rt.step_complete(run_id, "anything")
    assert result["action"] == "failed"
    assert "boom" in result["error"]


def test_top_level_branch_on_errors_clearly():
    from clops import branch_on

    class A(Op):
        Input = M
        Output = R
        Intent = "A."
        Meta = "Test fixture Op for validating top-level branch_on error."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating top-level branch_on error."
        body = branch_on(key=lambda _: "a", arms={"a": A})

    rt = Runtime()
    with pytest.raises(RuntimeError_, match="Top-level body=branch_on"):
        rt.start("P", "x")


# ---- gather (parallel) execution ------------------------------------


def test_gather_returns_dispatch_parallel_and_synthesizes_in_order():
    """Happy path: seed → gather(A, B, C) → synthesize receives [a, b, c]."""
    from clops import gather

    class Seed(Op):
        Input = M
        Output = R
        Intent = "s"
        Meta = "Test fixture Op for validating gather."

    class A(Op):
        Input = R
        Output = R
        Intent = "a"
        Meta = "Test fixture Op for validating gather."

    class B(Op):
        Input = R
        Output = R
        Intent = "b"
        Meta = "Test fixture Op for validating gather."

    class C(Op):
        Input = R
        Output = R
        Intent = "c"
        Meta = "Test fixture Op for validating gather."

    class Synth(Op):
        Input = R  # receives a list; Concept is loose
        Output = R
        Intent = "syn"
        Meta = "Test fixture Op for validating gather."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating gather."
        body = sequence(Seed, gather(A, B, C), Synth)
        entry = True

    rt = Runtime()
    d = rt.start("P", "x", enforce_entry=True)
    run_id = d["run_id"]

    # Seed
    persona_complete(rt, _pending_id(rt, run_id), "seed")
    parallel = rt.step_complete(run_id, "seed")
    assert parallel["action"] == "dispatch_parallel"
    assert parallel["report_via"] == "step_complete_parallel"
    exec_ids = parallel["execution_ids"]
    assert len(exec_ids) == 3
    assert len(parallel["agent_configs"]) == 3

    # Feed outputs (dict keyed by execution_id)
    results = {
        exec_ids[0]: "a-out",
        exec_ids[1]: "b-out",
        exec_ids[2]: "c-out",
    }
    d2 = rt.step_complete_parallel(run_id, results)
    # Synth dispatched next; its prompt's "Your input" should carry the list.
    assert d2["action"] == "dispatch"
    assert d2["agent_config"]["description"].startswith("Execute Synth")
    assert "a-out" in d2["agent_config"]["prompt"]
    assert "b-out" in d2["agent_config"]["prompt"]
    assert "c-out" in d2["agent_config"]["prompt"]

    persona_complete(rt, _pending_id(rt, run_id), "final")
    done = rt.step_complete(run_id, "final")
    assert done["action"] == "done"

    # State graph: 5 executions (Seed, A, B, C, Synth)
    counts = {}
    for e in rt.get_run(run_id).executions.values():
        counts[e.op_name] = counts.get(e.op_name, 0) + 1
    assert counts == {"Seed": 1, "A": 1, "B": 1, "C": 1, "Synth": 1}


def test_gather_prompts_each_branch_with_upstream_output():
    from clops import gather

    class Seed(Op):
        Input = M
        Output = R
        Intent = "s"
        Meta = "Test fixture Op for validating gather prompts."

    class A(Op):
        Input = R
        Output = R
        Intent = "a"
        Meta = "Test fixture Op for validating gather prompts."

    class B(Op):
        Input = R
        Output = R
        Intent = "b"
        Meta = "Test fixture Op for validating gather prompts."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating gather prompts."
        body = sequence(Seed, gather(A, B))
        entry = True

    rt = Runtime()
    d = rt.start("P", "x", enforce_entry=True)
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "the-seed-output")
    parallel = rt.step_complete(run_id, "the-seed-output")
    # Both branches' prompts should carry the same upstream output.
    for cfg in parallel["agent_configs"]:
        assert "the-seed-output" in cfg["prompt"]


def test_step_complete_parallel_missing_execution_ids_raises():
    from clops import gather

    class Seed(Op):
        Input = M
        Output = R
        Intent = "s"
        Meta = "Test fixture Op for validating parallel id validation."

    class A(Op):
        Input = R
        Output = R
        Intent = "a"
        Meta = "Test fixture Op for validating parallel id validation."

    class B(Op):
        Input = R
        Output = R
        Intent = "b"
        Meta = "Test fixture Op for validating parallel id validation."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating parallel id validation."
        body = sequence(Seed, gather(A, B))
        entry = True

    rt = Runtime()
    d = rt.start("P", "x", enforce_entry=True)
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "seed")
    parallel = rt.step_complete(run_id, "seed")
    ids = parallel["execution_ids"]

    # Only one of two
    with pytest.raises(RuntimeError_, match="missing execution_ids"):
        rt.step_complete_parallel(run_id, {ids[0]: "x"})

    # Extra id
    with pytest.raises(RuntimeError_, match="unexpected execution_ids"):
        rt.step_complete_parallel(run_id, {ids[0]: "x", ids[1]: "y", "exec_bogus": "z"})


def test_step_complete_parallel_without_active_gather_errors():
    from clops import gather

    class A(Op):
        Input = M
        Output = R
        Intent = "a"
        Meta = "Test fixture Op for validating no-active-gather error."

    class A2(Op):
        Input = R
        Output = R
        Intent = "a2"
        Meta = "Test fixture Op for validating no-active-gather error."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating no-active-gather error."
        body = sequence(A, A2)
        entry = True

    rt = Runtime()
    d = rt.start("P", "x", enforce_entry=True)
    run_id = d["run_id"]
    with pytest.raises(RuntimeError_, match="no active gather"):
        rt.step_complete_parallel(run_id, {})


def test_top_level_gather_errors_clearly():
    from clops import gather

    class A(Op):
        Input = M
        Output = R
        Intent = "a"
        Meta = "Test fixture Op for validating top-level gather error."

    class B(Op):
        Input = M
        Output = R
        Intent = "b"
        Meta = "Test fixture Op for validating top-level gather error."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating top-level gather error."
        body = gather(A, B)

    rt = Runtime()
    with pytest.raises(RuntimeError_, match="Top-level body=gather"):
        rt.start("P", "x")


def test_gather_accepts_composition_branches():
    """Issue #3: gather() branches may be composition Ops (multi-step tracks).

    gather(TrackA=seq(A1,A2), TrackB=seq(B1)) runs as batched parallel rounds:
    round 1 dispatches [A1, B1]; once B1 finishes, round 2 dispatches just [A2];
    outputs join in declaration order = [A2-out, B1-out].
    """
    from clops import gather

    class Seed(Op):
        Input = M
        Output = R
        Intent = "s"
        Meta = "Test fixture Op for validating composite gather branches."

    class A1(Op):
        Input = R
        Output = R
        Intent = "a1"
        Meta = "Test fixture Op for validating composite gather branches."

    class A2(Op):
        Input = R
        Output = R
        Intent = "a2"
        Meta = "Test fixture Op for validating composite gather branches."

    class B1(Op):
        Input = R
        Output = R
        Intent = "b1"
        Meta = "Test fixture Op for validating composite gather branches."

    class TrackA(Op):
        Input = R
        Output = R
        Intent = "Track A."
        Meta = "Test fixture composition Op for validating composite gather."
        body = sequence(A1, A2)

    class TrackB(Op):
        Input = R
        Output = R
        Intent = "Track B."
        Meta = "Test fixture composition Op for validating composite gather."
        body = sequence(B1)

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating composite gather branches."
        body = sequence(Seed, gather(TrackA, TrackB))
        entry = True

    rt = Runtime()
    d = rt.start("P", "x", enforce_entry=True)
    run_id = d["run_id"]

    persona_complete(rt, _pending_id(rt, run_id), "seed")
    round1 = rt.step_complete(run_id, "seed")
    # Round 1: each track's first leaf, in branch declaration order.
    assert round1["action"] == "dispatch_parallel"
    ids1 = round1["execution_ids"]
    assert len(ids1) == 2
    assert round1["agent_configs"][0]["description"].startswith("Execute A1")
    assert round1["agent_configs"][1]["description"].startswith("Execute B1")

    round2 = rt.step_complete_parallel(run_id, {ids1[0]: "a1-out", ids1[1]: "b1-out"})
    # TrackB is done; TrackA advances to A2 — a 1-leaf parallel round.
    assert round2["action"] == "dispatch_parallel"
    ids2 = round2["execution_ids"]
    assert len(ids2) == 1
    assert round2["agent_configs"][0]["description"].startswith("Execute A2")

    done = rt.step_complete_parallel(run_id, {ids2[0]: "a2-out"})
    assert done["action"] == "done"
    # Join is in branch declaration order: [TrackA output, TrackB output].
    assert done["output"] == ["a2-out", "b1-out"]

    counts: dict = {}
    for e in rt.get_run(run_id).executions.values():
        counts[e.op_name] = counts.get(e.op_name, 0) + 1
    assert counts == {"Seed": 1, "A1": 1, "A2": 1, "B1": 1}


def test_gather_leaf_and_composite_branches_mixed():
    """A gather may mix a leaf branch and a composite branch."""
    from clops import gather

    class Seed(Op):
        Input = M
        Output = R
        Intent = "s"
        Meta = "Test fixture Op for validating mixed gather branches."

    class Leaf(Op):
        Input = R
        Output = R
        Intent = "leaf"
        Meta = "Test fixture Op for validating mixed gather branches."

    class C1(Op):
        Input = R
        Output = R
        Intent = "c1"
        Meta = "Test fixture Op for validating mixed gather branches."

    class C2(Op):
        Input = R
        Output = R
        Intent = "c2"
        Meta = "Test fixture Op for validating mixed gather branches."

    class Track(Op):
        Input = R
        Output = R
        Intent = "Track."
        Meta = "Test fixture composition Op for mixed gather."
        body = sequence(C1, C2)

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating mixed gather branches."
        body = sequence(Seed, gather(Leaf, Track))
        entry = True

    rt = Runtime()
    d = rt.start("P", "x", enforce_entry=True)
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "seed")
    r1 = rt.step_complete(run_id, "seed")
    ids1 = r1["execution_ids"]
    assert r1["agent_configs"][0]["description"].startswith("Execute Leaf")
    assert r1["agent_configs"][1]["description"].startswith("Execute C1")

    r2 = rt.step_complete_parallel(run_id, {ids1[0]: "leaf-out", ids1[1]: "c1-out"})
    # Leaf done; Track advances to C2.
    assert r2["action"] == "dispatch_parallel"
    assert r2["agent_configs"][0]["description"].startswith("Execute C2")
    ids2 = r2["execution_ids"]

    done = rt.step_complete_parallel(run_id, {ids2[0]: "c2-out"})
    assert done["action"] == "done"
    assert done["output"] == ["leaf-out", "c2-out"]


# ---- Slice 3: dynamic calls inside gather branches --------------------


def test_gather_branch_can_call_subroutine():
    """Slice 3: a gather branch may make a dynamic sub-Op call. The branch's
    driver slot stays parked through the subroutine cycle while its peer branch
    completes; the join still preserves declaration order."""
    from clops import gather

    class Seed(Op):
        Input = M; Output = R
        Intent = "s"; Meta = "Test fixture Op for gather-subroutine."

    class Sub(Op):
        Input = R; Output = R
        Intent = "sub"; Meta = "Test fixture leaf sub-Op for gather-subroutine."

    class Caller(Op):
        Input = R; Output = R
        Intent = "caller"; Meta = "Test fixture Op for gather-subroutine."
        Tools = [Sub]

    class Plain(Op):
        Input = R; Output = R
        Intent = "plain"; Meta = "Test fixture Op for gather-subroutine."

    class P(Op):
        Input = M; Output = R
        Intent = "P."; Meta = "Test fixture Op for gather-subroutine."
        body = sequence(Seed, gather(Caller, Plain))
        entry = True

    rt = Runtime()
    d = rt.start("P", "x", enforce_entry=True)
    run_id = d["run_id"]

    persona_complete(rt, _pending_id(rt, run_id), "seed")
    round1 = rt.step_complete(run_id, "seed")
    assert round1["action"] == "dispatch_parallel"
    caller_id, plain_id = round1["execution_ids"]
    assert round1["agent_configs"][0]["description"].startswith("Execute Caller")

    # The Caller branch makes a dynamic call; the Plain branch completes normally.
    rt.call_op(caller_id, "Sub", Sub, "sub-input")
    persona_complete(rt, plain_id, "plain-out")
    round2 = rt.step_complete_parallel(
        run_id, {caller_id: "calling", plain_id: "plain-out"}
    )
    # Still mid-gather: the sub-Op is dispatched as the next parallel round.
    assert round2["action"] == "dispatch_parallel"
    assert round2["report_via"] == "step_complete_parallel"
    assert len(round2["execution_ids"]) == 1
    sub_id = round2["execution_ids"][0]
    assert round2["agent_configs"][0]["description"].startswith("Execute Sub")
    assert "sub-input" in round2["agent_configs"][0]["prompt"]

    # Sub completes → the Caller branch is re-dispatched with the result.
    persona_complete(rt, sub_id, "sub-out")
    round3 = rt.step_complete_parallel(run_id, {sub_id: "sub-out"})
    assert round3["action"] == "dispatch_parallel"
    redispatch_id = round3["execution_ids"][0]
    assert redispatch_id == caller_id  # same execution re-dispatched
    assert round3["agent_configs"][0]["description"].startswith("Execute Caller")
    assert "Result from Sub" in round3["agent_configs"][0]["prompt"]
    assert "sub-out" in round3["agent_configs"][0]["prompt"]

    # Caller finishes → the gather joins in declaration order [Caller, Plain].
    persona_complete(rt, caller_id, "caller-out")
    done = rt.step_complete_parallel(run_id, {caller_id: "caller-out"})
    assert done["action"] == "done"
    assert done["output"] == ["caller-out", "plain-out"]


def test_gather_branch_nested_subroutine():
    """A gather branch's sub-Op may itself call a deeper sub-Op; the whole
    nested cycle unfolds underneath the parked branch slot."""
    from clops import gather

    class Seed(Op):
        Input = M; Output = R
        Intent = "s"; Meta = "Test fixture Op for nested gather-subroutine."

    class Deep(Op):
        Input = R; Output = R
        Intent = "deep"; Meta = "Test fixture leaf sub-Op for nested gather-subroutine."

    class Mid(Op):
        Input = R; Output = R
        Intent = "mid"; Meta = "Test fixture sub-Op for nested gather-subroutine."
        Tools = [Deep]

    class Caller(Op):
        Input = R; Output = R
        Intent = "caller"; Meta = "Test fixture Op for nested gather-subroutine."
        Tools = [Mid]

    class Plain(Op):
        Input = R; Output = R
        Intent = "plain"; Meta = "Test fixture Op for nested gather-subroutine."

    class P(Op):
        Input = M; Output = R
        Intent = "P."; Meta = "Test fixture Op for nested gather-subroutine."
        body = sequence(Seed, gather(Caller, Plain))
        entry = True

    rt = Runtime()
    d = rt.start("P", "x", enforce_entry=True)
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "seed")
    round1 = rt.step_complete(run_id, "seed")
    caller_id, plain_id = round1["execution_ids"]

    # Caller → Mid (the peer Plain branch completes immediately).
    rt.call_op(caller_id, "Mid", Mid, "to-mid")
    persona_complete(rt, plain_id, "plain-out")
    r2 = rt.step_complete_parallel(run_id, {caller_id: "calling-mid", plain_id: "plain-out"})
    mid_id = r2["execution_ids"][0]
    assert r2["agent_configs"][0]["description"].startswith("Execute Mid")

    # Mid → Deep (a nested dynamic call from inside the subroutine)
    rt.call_op(mid_id, "Deep", Deep, "to-deep")
    r3 = rt.step_complete_parallel(run_id, {mid_id: "calling-deep"})
    deep_id = r3["execution_ids"][0]
    assert r3["agent_configs"][0]["description"].startswith("Execute Deep")

    # Deep completes → Mid re-dispatched → Mid completes → Caller re-dispatched.
    persona_complete(rt, deep_id, "deep-out")
    r4 = rt.step_complete_parallel(run_id, {deep_id: "deep-out"})
    assert r4["execution_ids"][0] == mid_id
    assert "deep-out" in r4["agent_configs"][0]["prompt"]

    persona_complete(rt, mid_id, "mid-out")
    r5 = rt.step_complete_parallel(run_id, {mid_id: "mid-out"})
    assert r5["execution_ids"][0] == caller_id
    assert "mid-out" in r5["agent_configs"][0]["prompt"]

    persona_complete(rt, caller_id, "caller-out")
    done = rt.step_complete_parallel(run_id, {caller_id: "caller-out"})
    assert done["action"] == "done"
    assert done["output"] == ["caller-out", "plain-out"]


def test_gather_branch_composite_subroutine():
    """A composite (multi-step) sub-Op called from inside a gather branch runs in
    the same run beneath the parked branch slot — the driver-native Invoke lifts
    the restriction for composite callees too, not just leaves."""
    from clops import gather

    class Seed(Op):
        Input = M; Output = R
        Intent = "s"; Meta = "Test fixture Op for composite-in-gather."

    class Inner(Op):
        Input = R; Output = R
        Intent = "inner"; Meta = "Test fixture Op for composite-in-gather."

    class CompositeSub(Op):
        Input = R; Output = R
        Intent = "composite"; Meta = "Test fixture composite sub-Op for composite-in-gather."
        body = sequence(Inner)

    class Caller(Op):
        Input = R; Output = R
        Intent = "caller"; Meta = "Test fixture Op for composite-in-gather."
        Tools = [CompositeSub]

    class Plain(Op):
        Input = R; Output = R
        Intent = "plain"; Meta = "Test fixture Op for composite-in-gather."

    class P(Op):
        Input = M; Output = R
        Intent = "P."; Meta = "Test fixture Op for composite-in-gather."
        body = sequence(Seed, gather(Caller, Plain))
        entry = True

    rt = Runtime()
    d = rt.start("P", "x", enforce_entry=True)
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "seed")
    round1 = rt.step_complete(run_id, "seed")
    caller_id, plain_id = round1["execution_ids"]

    # The Caller branch invokes the composite; the Plain branch completes.
    rt.call_op(caller_id, "CompositeSub", CompositeSub, "in")
    persona_complete(rt, plain_id, "plain-out")
    round2 = rt.step_complete_parallel(
        run_id, {caller_id: "calling", plain_id: "plain-out"}
    )
    # The composite's first leaf (Inner) dispatches as the next parallel round.
    assert round2["action"] == "dispatch_parallel"
    assert len(round2["execution_ids"]) == 1
    inner_id = round2["execution_ids"][0]
    assert round2["agent_configs"][0]["description"].startswith("Execute Inner")

    # Inner completes → composite returns → Caller branch re-dispatched.
    persona_complete(rt, inner_id, "inner-out")
    round3 = rt.step_complete_parallel(run_id, {inner_id: "inner-out"})
    assert round3["execution_ids"] == [caller_id]
    assert "inner-out" in round3["agent_configs"][0]["prompt"]

    # Caller completes → gather joins in declaration order.
    persona_complete(rt, caller_id, "caller-out")
    done = rt.step_complete_parallel(run_id, {caller_id: "caller-out"})
    assert done["action"] == "done"
    assert done["output"] == ["caller-out", "plain-out"]


def test_branch_on_arm_can_be_a_bare_sequence():
    """Issue #1: a branch_on arm that is a bare sequence(...) — not wrapped in an
    Op — executes as a multi-step branch instead of raising 'Unsupported step'."""
    from clops import branch_on

    class Up(Op):
        Input = M
        Output = R
        Intent = "Up."
        Meta = "Test fixture Op for validating bare-sequence branch arm."

    class X1(Op):
        Input = R
        Output = R
        Intent = "x1."
        Meta = "Test fixture Op for validating bare-sequence branch arm."

    class X2(Op):
        Input = R
        Output = R
        Intent = "x2."
        Meta = "Test fixture Op for validating bare-sequence branch arm."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating bare-sequence branch arm."
        body = sequence(
            Up,
            branch_on(key=lambda _: "go", arms={"go": sequence(X1, X2)}),
        )

    rt = Runtime()
    d = rt.start("P", "x")
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "from-up")
    d2 = rt.step_complete(run_id, "from-up")
    assert d2["agent_config"]["description"].startswith("Execute X1")
    persona_complete(rt, _pending_id(rt, run_id), "x1-out")
    d3 = rt.step_complete(run_id, "x1-out")
    assert d3["agent_config"]["description"].startswith("Execute X2")
    persona_complete(rt, _pending_id(rt, run_id), "x2-out")
    done = rt.step_complete(run_id, "x2-out")
    assert done["action"] == "done"
    assert done["output"] == "x2-out"


def test_branch_on_arm_can_be_sequence_with_gather():
    """Issue #1 exact repro: a branch arm = sequence(gather(OpA, OpB), Assemble).

    The bare sequence runs; its first step is a gather (parallel), then Assemble."""
    from clops import branch_on, gather

    class Check(Op):
        Input = M
        Output = R
        Intent = "check."
        Meta = "Test fixture Op for validating issue #1 repro."

    class OpA(Op):
        Input = R
        Output = R
        Intent = "a."
        Meta = "Test fixture Op for validating issue #1 repro."

    class OpB(Op):
        Input = R
        Output = R
        Intent = "b."
        Meta = "Test fixture Op for validating issue #1 repro."

    class Assemble(Op):
        Input = R
        Output = R
        Intent = "assemble."
        Meta = "Test fixture Op for validating issue #1 repro."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating issue #1 repro."
        body = sequence(
            Check,
            branch_on(
                key=lambda _: "path_b",
                arms={
                    "path_a": Assemble,
                    "path_b": sequence(gather(OpA, OpB), Assemble),
                },
            ),
        )
        entry = True

    rt = Runtime()
    d = rt.start("P", "x", enforce_entry=True)
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "checked")
    parallel = rt.step_complete(run_id, "checked")
    assert parallel["action"] == "dispatch_parallel"
    ids = parallel["execution_ids"]
    assert len(ids) == 2

    after = rt.step_complete_parallel(run_id, {ids[0]: "a-out", ids[1]: "b-out"})
    # gather joins → Assemble dispatched with the [a, b] list as input.
    assert after["action"] == "dispatch"
    assert after["agent_config"]["description"].startswith("Execute Assemble")
    assert "a-out" in after["agent_config"]["prompt"]
    assert "b-out" in after["agent_config"]["prompt"]

    persona_complete(rt, _pending_id(rt, run_id), "assembled")
    done = rt.step_complete(run_id, "assembled")
    assert done["action"] == "done"
    assert done["output"] == "assembled"


def test_gather_branch_failure_fails_the_run():
    """If any branch enters FAILED state (e.g. via need) the gather fails."""
    from clops import gather

    class Seed(Op):
        Input = M
        Output = R
        Intent = "s"
        Meta = "Test fixture Op for validating gather branch failure."

    class A(Op):
        Input = R
        Output = R
        Intent = "a"
        Meta = "Test fixture Op for validating gather branch failure."

    class B(Op):
        Input = R
        Output = R
        Intent = "b"
        Meta = "Test fixture Op for validating gather branch failure."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating gather branch failure."
        body = sequence(Seed, gather(A, B))
        entry = True

    rt = Runtime()
    d = rt.start("P", "x", enforce_entry=True)
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "seed")
    parallel = rt.step_complete(run_id, "seed")
    ids = parallel["execution_ids"]

    # A completes; B calls need.
    rt.complete(ids[0], "a-out")
    rt.need(ids[1], "bad input")

    result = rt.step_complete_parallel(run_id, {ids[0]: "a-out", ids[1]: None})
    assert result["action"] == "failed"
    assert "bad input" in result["error"]


# ---- loop execution -------------------------------------------------


def test_loop_terminates_when_until_returns_true():
    """Loop dispatches body, checks until against output, terminates when truthy."""
    from clops import loop

    class Seed(Op):
        Input = M
        Output = R
        Intent = "Seed."
        Meta = "Test fixture Op for validating loop termination."

    class Step(Op):
        Input = R
        Output = R
        Intent = "Step."
        Meta = "Test fixture Op for validating loop termination."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating loop termination."
        body = sequence(
            Seed,
            loop(body=Step, until=lambda out: "[done]" in str(out)),
        )

    rt = Runtime()
    d = rt.start("P", "x")
    run_id = d["run_id"]

    # Seed
    persona_complete(rt, _pending_id(rt, run_id), "v0")
    d = rt.step_complete(run_id, "v0")
    # First loop iteration: dispatched
    assert d["action"] == "dispatch"
    assert d["agent_config"]["description"].startswith("Execute Step")
    persona_complete(rt, _pending_id(rt, run_id), "v1")
    d = rt.step_complete(run_id, "v1")
    # until still false → another iteration
    assert d["action"] == "dispatch"
    persona_complete(rt, _pending_id(rt, run_id), "v2 [done]")
    done = rt.step_complete(run_id, "v2 [done]")
    # until now true → loop terminates → run done
    assert done["action"] == "done"
    assert done["output"] == "v2 [done]"

    # State graph: Seed + 2 Step executions
    op_counts: dict = {}
    for e in rt.get_run(run_id).executions.values():
        op_counts[e.op_name] = op_counts.get(e.op_name, 0) + 1
    assert op_counts == {"Seed": 1, "Step": 2}


def test_loop_respects_max_iterations():
    """Loop fails the run if max_iterations is hit without satisfying until."""
    from clops import loop

    class Seed(Op):
        Input = M
        Output = R
        Intent = "Seed."
        Meta = "Test fixture Op for validating loop max_iterations."

    class Step(Op):
        Input = R
        Output = R
        Intent = "Step."
        Meta = "Test fixture Op for validating loop max_iterations."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating loop max_iterations."
        body = sequence(
            Seed,
            loop(body=Step, until=lambda _: False, max_iterations=3),
        )

    rt = Runtime()
    d = rt.start("P", "x")
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "seed")
    rt.step_complete(run_id, "seed")
    # Iterate 3 times; predicate always false; 4th attempt should fail.
    for i in range(3):
        persona_complete(rt, _pending_id(rt, run_id), f"v{i}")
        result = rt.step_complete(run_id, f"v{i}")
        if result["action"] == "failed":
            break
    assert result["action"] == "failed"
    assert "max_iterations" in result["error"]
    assert "(3)" in result["error"]


def test_loop_until_predicate_exception_fails_run():
    from clops import loop

    class Seed(Op):
        Input = M
        Output = R
        Intent = "Seed."
        Meta = "Test fixture Op for validating loop predicate exception."

    class Step(Op):
        Input = R
        Output = R
        Intent = "Step."
        Meta = "Test fixture Op for validating loop predicate exception."

    def _bad_until(_):
        raise ValueError("predicate boom")

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating loop predicate exception."
        body = sequence(Seed, loop(body=Step, until=_bad_until))

    rt = Runtime()
    d = rt.start("P", "x")
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "seed")
    rt.step_complete(run_id, "seed")
    persona_complete(rt, _pending_id(rt, run_id), "v0")
    result = rt.step_complete(run_id, "v0")
    assert result["action"] == "failed"
    assert "predicate boom" in result["error"]


def test_loop_body_must_be_op():
    from clops import loop

    class Seed(Op):
        Input = M
        Output = R
        Intent = "Seed."
        Meta = "Test fixture Op for validating loop body type check."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating loop body type check."
        body = sequence(Seed, loop(body="not_an_op", until=lambda _: True))

    rt = Runtime()
    d = rt.start("P", "x")
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "seed")
    result = rt.step_complete(run_id, "seed")
    assert result["action"] == "failed"
    assert "loop body must be an Op" in result["error"]


def test_loop_factory_validates_max_iterations():
    from clops import loop

    class Body(Op):
        Input = M
        Output = R
        Intent = "b."
        Meta = "Test fixture Op for validating loop factory."

    with pytest.raises(ValueError):
        loop(body=Body, until=lambda _: True, max_iterations=0)


def test_top_level_loop_errors_clearly():
    from clops import loop

    class Body(Op):
        Input = M
        Output = R
        Intent = "b."
        Meta = "Test fixture Op for validating top-level loop error."

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating top-level loop error."
        body = loop(body=Body, until=lambda _: True)

    rt = Runtime()
    with pytest.raises(RuntimeError_, match="Top-level body=loop"):
        rt.start("P", "x")


def test_loop_resets_iteration_counter_when_done():
    """After a loop terminates, the counter resets so a downstream loop
    in the same sequence starts fresh."""
    from clops import loop

    class Seed(Op):
        Input = M
        Output = R
        Intent = "Seed."
        Meta = "Test fixture Op for validating loop counter reset."

    class StepA(Op):
        Input = R
        Output = R
        Intent = "A."
        Meta = "Test fixture Op for validating loop counter reset."

    class StepB(Op):
        Input = R
        Output = R
        Intent = "B."
        Meta = "Test fixture Op for validating loop counter reset."

    class P(Op):
        Input = M
        Output = R
        Intent = "Two loops in sequence."
        Meta = "Test fixture Op for validating loop counter reset."
        body = sequence(
            Seed,
            loop(body=StepA, until=lambda x: "a-done" in str(x)),
            loop(body=StepB, until=lambda x: "b-done" in str(x)),
        )

    rt = Runtime()
    d = rt.start("P", "x")
    run_id = d["run_id"]
    persona_complete(rt, _pending_id(rt, run_id), "seed")
    rt.step_complete(run_id, "seed")
    # First loop, one iteration
    persona_complete(rt, _pending_id(rt, run_id), "a-done")
    d = rt.step_complete(run_id, "a-done")
    # Second loop should now be dispatching, not the first re-iterating
    assert d["action"] == "dispatch"
    assert d["agent_config"]["description"].startswith("Execute StepB")
    persona_complete(rt, _pending_id(rt, run_id), "b-done")
    done = rt.step_complete(run_id, "b-done")
    assert done["action"] == "done"


def test_branch_on_arm_can_be_a_composition(branch_library):
    """The chosen arm may itself be a composition Op (the interpreter recurses)."""
    from clops import branch_on

    class Up(Op):
        Input = M
        Output = R
        Intent = "Up."
        Meta = "Test fixture Op for validating composed branch arm."

    class Inner1(Op):
        Input = R
        Output = R
        Intent = "i1."
        Meta = "Test fixture Op for validating composed branch arm."

    class Inner2(Op):
        Input = R
        Output = R
        Intent = "i2."
        Meta = "Test fixture Op for validating composed branch arm."

    class Composed(Op):
        Input = R
        Output = R
        Intent = "Composed arm."
        Meta = "Test fixture Op for validating composed branch arm."
        body = sequence(Inner1, Inner2)

    class P(Op):
        Input = M
        Output = R
        Intent = "P."
        Meta = "Test fixture Op for validating composed branch arm."
        body = sequence(Up, branch_on(key=lambda _: "go", arms={"go": Composed}))

    rt = Runtime()
    d = rt.start("P", "x")
    run_id = d["run_id"]

    persona_complete(rt, _pending_id(rt, run_id), "from-up")
    d2 = rt.step_complete(run_id, "from-up")
    assert d2["agent_config"]["description"].startswith("Execute Inner1")

    persona_complete(rt, _pending_id(rt, run_id), "i1-out")
    d3 = rt.step_complete(run_id, "i1-out")
    assert d3["agent_config"]["description"].startswith("Execute Inner2")

    persona_complete(rt, _pending_id(rt, run_id), "i2-out")
    done = rt.step_complete(run_id, "i2-out")
    assert done["action"] == "done"
    assert done["output"] == "i2-out"


# ---- Manifest output contract ----------------------------------------


def _manifest_runtime() -> Runtime:
    rt = Runtime()
    rt._settings = {"output_contract": "manifest"}
    return rt


def test_manifest_lightens_intermediate_sequence_steps_only():
    """Intermediate steps emit a manifest; the terminal step (the run output)
    keeps the full-output contract."""

    class SM(Concept):
        description = "m"

    class SR(Concept):
        description = "r"

    class MStep1(Op):
        Input = SM; Output = SR; Intent = "one"; Meta = "manifest seq fixture"

    class MStep2(Op):
        Input = SR; Output = SR; Intent = "two"; Meta = "manifest seq fixture"

    class MStep3(Op):
        Input = SR; Output = SR; Intent = "three"; Meta = "manifest seq fixture"

    class MThreeStep(Op):
        Input = SM; Output = SR; Intent = "seq"; Meta = "manifest seq fixture"
        body = sequence(MStep1, MStep2, MStep3)
        entry = True

    rt = _manifest_runtime()
    d1 = rt.start("MThreeStep", "in")
    assert _holds(d1) and not _full(d1)  # step 1 -> manifest

    persona_complete(rt, _pending_id(rt, d1["run_id"]), "s1")
    d2 = rt.step_complete(d1["run_id"], "s1")
    assert _holds(d2) and not _full(d2)  # step 2 -> manifest

    persona_complete(rt, _pending_id(rt, d2["run_id"]), "s2")
    d3 = rt.step_complete(d2["run_id"], "s2")
    assert _full(d3) and not _holds(d3)  # terminal step -> full

    persona_complete(rt, _pending_id(rt, d3["run_id"]), "s3")
    done = rt.step_complete(d3["run_id"], "s3")
    assert done["action"] == "done"


def test_manifest_keeps_branch_key_step_and_handler_full():
    """A step feeding a branch_on key stays full (the key runs on str(output)),
    and the handler arm is terminal so it stays full too."""

    class BM(Concept):
        description = "m"

    class BC(Concept):
        description = "cat"

    class BRep(Concept):
        description = "reply"

    class BTriage(Op):
        Input = BM; Output = BC; Intent = "classify"; Meta = "manifest branch fixture"

    class BHandleX(Op):
        Input = BC; Output = BRep; Intent = "x"; Meta = "manifest branch fixture"

    class BHandleY(Op):
        Input = BC; Output = BRep; Intent = "y"; Meta = "manifest branch fixture"

    def _key(out):
        return "x" if "x" in str(out) else "y"

    class BRoute(Op):
        Input = BM; Output = BRep; Intent = "route"; Meta = "manifest branch fixture"
        body = sequence(
            BTriage,
            branch_on(key=_key, arms={"x": BHandleX, "y": BHandleY}),
        )
        entry = True

    rt = _manifest_runtime()
    d1 = rt.start("BRoute", "go")
    assert d1["agent_config"]["description"].startswith("Execute BTriage")
    assert _full(d1) and not _holds(d1)  # feeds branch_on key -> full

    persona_complete(rt, _pending_id(rt, d1["run_id"]), "x")
    d2 = rt.step_complete(d1["run_id"], "x")
    assert d2["agent_config"]["description"].startswith("Execute BHandleX")
    assert _full(d2) and not _holds(d2)  # terminal handler -> full


def test_manifest_keeps_loop_seed_and_body_full():
    """The seed feeding a loop and the loop body (accumulator + until) stay full."""

    class LT(Concept):
        description = "topic"

    class LB(Concept):
        description = "benefits"

    class LSeed(Op):
        Input = LT; Output = LB; Intent = "seed"; Meta = "manifest loop fixture"

    class LRefine(Op):
        Input = LB; Output = LB; Intent = "refine"; Meta = "manifest loop fixture"

    class LBrainstorm(Op):
        Input = LT; Output = LB; Intent = "brainstorm"; Meta = "manifest loop fixture"
        body = sequence(
            LSeed,
            loop(body=LRefine, until=lambda o: "[done]" in str(o), max_iterations=3),
        )
        entry = True

    rt = _manifest_runtime()
    d1 = rt.start("LBrainstorm", "ai")
    assert d1["agent_config"]["description"].startswith("Execute LSeed")
    assert _full(d1) and not _holds(d1)  # feeds the loop -> full

    persona_complete(rt, _pending_id(rt, d1["run_id"]), "b1")
    d2 = rt.step_complete(d1["run_id"], "b1")
    assert d2["agent_config"]["description"].startswith("Execute LRefine")
    assert _full(d2) and not _holds(d2)  # loop body -> full

    persona_complete(rt, _pending_id(rt, d2["run_id"]), "b2 [done]")
    done = rt.step_complete(d2["run_id"], "b2 [done]")
    assert done["action"] == "done"


def test_full_contract_is_the_default_without_settings():
    """Without the manifest setting, every step uses the full-output contract."""

    class DM(Concept):
        description = "m"

    class DR(Concept):
        description = "r"

    class DStep1(Op):
        Input = DM; Output = DR; Intent = "one"; Meta = "default contract fixture"

    class DStep2(Op):
        Input = DR; Output = DR; Intent = "two"; Meta = "default contract fixture"

    class DTwoStep(Op):
        Input = DM; Output = DR; Intent = "seq"; Meta = "default contract fixture"
        body = sequence(DStep1, DStep2)
        entry = True

    rt = Runtime()  # no manifest setting
    d1 = rt.start("DTwoStep", "in")
    assert _full(d1) and not _holds(d1)

    persona_complete(rt, _pending_id(rt, d1["run_id"]), "s1")
    d2 = rt.step_complete(d1["run_id"], "s1")
    assert _full(d2) and not _holds(d2)


def test_manifest_gather_branch_deliverables_full_internals_light():
    """Under manifest mode: a gather branch's deliverable (terminal output)
    stays full so the join gets real values, while branch-internal steps and
    the step feeding the gather stay light."""
    from clops import gather

    class GM(Concept):
        description = "m"

    class GR(Concept):
        description = "r"

    class GSeed(Op):
        Input = GM; Output = GR; Intent = "s"; Meta = "manifest gather fixture"

    class GA1(Op):
        Input = GR; Output = GR; Intent = "a1"; Meta = "manifest gather fixture"

    class GA2(Op):
        Input = GR; Output = GR; Intent = "a2"; Meta = "manifest gather fixture"

    class GB(Op):
        Input = GR; Output = GR; Intent = "b"; Meta = "manifest gather fixture"

    class GSynth(Op):
        Input = GR; Output = GR; Intent = "syn"; Meta = "manifest gather fixture"

    class GFlow(Op):
        Input = GM; Output = GR; Intent = "flow"; Meta = "manifest gather fixture"
        body = sequence(GSeed, gather(sequence(GA1, GA2), GB), GSynth)
        entry = True

    rt = _manifest_runtime()
    d1 = rt.start("GFlow", "x")
    # Seed feeds the gather (agent-consumed fan-out) -> manifest.
    assert _holds(d1) and not _full(d1)

    persona_complete(rt, _pending_id(rt, d1["run_id"]), "seed")
    r1 = rt.step_complete(d1["run_id"], "seed")
    assert r1["action"] == "dispatch_parallel"
    # Round 1: [GA1 (branch-internal -> manifest), GB (single-step deliverable -> full)].
    prompt_by_op = {
        c["description"].split()[1]: c["prompt"] for c in r1["agent_configs"]
    }
    assert "## What to hold by the end" in prompt_by_op["GA1"]   # internal -> light
    assert "## What you'll produce" in prompt_by_op["GB"]        # deliverable -> full

    ids1 = r1["execution_ids"]
    r2 = rt.step_complete_parallel(
        d1["run_id"], {ids1[0]: "x1", ids1[1]: "b-out"}
    )
    # Round 2: [GA2 (the track's deliverable -> full)].
    assert r2["action"] == "dispatch_parallel"
    assert "## What you'll produce" in r2["agent_configs"][0]["prompt"]

    ids2 = r2["execution_ids"]
    d_synth = rt.step_complete_parallel(d1["run_id"], {ids2[0]: "a-out"})
    # Synth is terminal -> full.
    assert d_synth["agent_config"]["description"].startswith("Execute GSynth")
    assert _full(d_synth) and not _holds(d_synth)
