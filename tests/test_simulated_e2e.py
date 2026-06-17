"""Simulated end-to-end tests — no LLM, no Claude Code, no real transports.

These tests stitch together every layer of Phase 1b runtime as one
coherent narrative:

    main thread → MCP server handlers → Runtime
                ← dispatch instruction ←
    main thread relays to "subagent"
       (here: a scripted MockSubagent that calls the same handlers)
    subagent → MCP handlers → Runtime
       complete / call_tool routed through the actual server methods
    SubagentStop hook fires
       → hook_server.decide() against the live Runtime
    main thread → step_complete → next dispatch or done

This is a Layer 2.5 test: full system wiring, fully deterministic.
Catches integration regressions that single-handler tests miss.
"""

from __future__ import annotations

import re
from typing import Any, Callable

import pytest

from clops import Concept, Op, Tool, sequence
from clops.runtime.hook_server import decide
from clops.runtime.mcp_server import FlowServer, ServerConfig


# ---- Concepts and tools used by the simulated library ---------------


class UserMessage(Concept):
    description = "A user-supplied message string."


class Classification(Concept):
    description = "A category label produced by classifier."


class Response(Concept):
    description = "A drafted response string."


# ---- Fixtures --------------------------------------------------------


@pytest.fixture
def server_with_pipeline():
    """A two-stage pipeline (Classify -> Draft) plus an external lookup tool."""

    lookup = Tool(
        name="lookup_history",
        description="Return mock history for a customer id.",
        parameters={"customer_id": str},
        handler=lambda customer_id: [{"customer_id": customer_id, "events": ["payment"]}],
    )

    class Classify(Op):
        Input = UserMessage
        Output = Classification
        Intent = "Classify the message as billing or technical."
        Meta = "Test fixture Op for validating E2E pipeline."
        Tools = [lookup]

    class Draft(Op):
        Input = Classification
        Output = Response
        Intent = "Draft a response based on the classification."
        Meta = "Test fixture Op for validating E2E pipeline."

    class Pipeline(Op):
        Input = UserMessage
        Output = Response
        Intent = "Classify then draft."
        Meta = "Test fixture Op for validating E2E pipeline."
        body = sequence(Classify, Draft)
        entry = True

    srv = FlowServer(ServerConfig())
    return srv, Classify, Draft, Pipeline


# ---- Mock subagent: reads its dispatch, runs a scripted plan -------


class MockSubagent:
    """A scripted subagent. Pretends to be a clops-executor running
    against the FlowServer's handler surface.

    The subagent extracts its execution_id from the dispatch prompt
    (just as a real one would by reading it), then runs a per-test
    `plan`: a sequence of MCP calls. The plan is a list of (tool_name,
    args_factory) where args_factory takes the MockSubagent and returns
    the args dict, so the plan can reference `self.execution_id`.
    """

    EXECUTION_ID_RE = re.compile(r'execution_id="(exec_[a-f0-9]+)"')

    def __init__(self, server: FlowServer, parent_session_id: str = "parent-main"):
        self.server = server
        self.parent_session_id = parent_session_id
        self.execution_id: str | None = None
        self.calls: list[tuple[str, dict, Any]] = []

    def run(self, dispatch: dict, plan: list[tuple[str, Callable[["MockSubagent"], dict]]]) -> str:
        prompt = dispatch["agent_config"]["prompt"]
        match = self.EXECUTION_ID_RE.search(prompt)
        assert match, f"prompt missing execution_id literal:\n{prompt}"
        self.execution_id = match.group(1)

        final_text = ""
        for tool_name, args_factory in plan:
            args = args_factory(self)
            args.setdefault("_parent_session_id", self.parent_session_id)
            handler = self.server._resolve_tool(tool_name)
            assert handler is not None, f"unknown tool {tool_name!r}"
            result = handler(args)
            self.calls.append((tool_name, args, result))
            if tool_name == "complete":
                final_text = str(args.get("output", ""))
            elif tool_name == "need":
                final_text = f"need: {args.get('reason')}"
        return final_text


# ---- Helpers ---------------------------------------------------------


def _hook_fires(server: FlowServer, parent_session_id: str) -> dict:
    """Simulate Claude Code firing SubagentStop for the given session."""
    return decide(server.runtime, {"session_id": parent_session_id})


# ---- The simulated runs ---------------------------------------------


def test_e2e_single_leaf_run_full_lifecycle(server_with_pipeline):
    srv, Classify, Draft, Pipeline = server_with_pipeline

    # 1. Main thread starts the process via MCP.
    dispatch = srv._handle_start_process({"process": "Pipeline", "input": "I was double charged"})
    assert dispatch["action"] == "dispatch"
    assert dispatch["agent_template"] == "clops-executor"

    # 2. First leaf is Classify — main thread "relays" to a subagent.
    sub = MockSubagent(srv)
    final = sub.run(
        dispatch,
        plan=[
            ("call_tool", lambda s: {
                "execution_id": s.execution_id,
                "name": "lookup_history",
                "arguments": {"customer_id": "cust_42"},
            }),
            ("complete", lambda s: {"execution_id": s.execution_id, "output": "billing"}),
        ],
    )
    assert final == "billing"

    # call_tool produced the handler's return value.
    call_results = [r for (name, _, r) in sub.calls if name == "call_tool"]
    assert call_results == [[{"customer_id": "cust_42", "events": ["payment"]}]]

    # 3. SubagentStop hook fires for that parent session.
    assert _hook_fires(srv, "parent-main") == {}

    # 4. Main thread reports back; runtime advances to the next leaf.
    next_dispatch = srv._handle_step_complete({"run_id": dispatch["run_id"], "result": final})
    assert next_dispatch["action"] == "dispatch"
    assert next_dispatch["agent_config"]["description"].startswith("Execute Draft")
    # Draft's input prompt should include the upstream output.
    assert "billing" in next_dispatch["agent_config"]["prompt"]

    # 5. Second leaf is Draft — another subagent.
    sub2 = MockSubagent(srv)
    final2 = sub2.run(
        next_dispatch,
        plan=[
            ("complete", lambda s: {
                "execution_id": s.execution_id,
                "output": "Sorry about the double charge — refunding now.",
            }),
        ],
    )

    # 6. Second SubagentStop fires.
    assert _hook_fires(srv, "parent-main") == {}

    # 7. Main reports back; run completes.
    done = srv._handle_step_complete({"run_id": dispatch["run_id"], "result": final2})
    assert done["action"] == "done"
    assert "double charge" in done["output"]

    # 8. Final state graph is what we expect.
    status = srv._handle_run_status({"run_id": dispatch["run_id"]})
    assert status["status"] == "completed"
    assert status["pending_executions"] == []
    assert [e["op_name"] for e in status["executions"]] == ["Classify", "Draft"]
    assert all(e["status"] == "completed" for e in status["executions"])


def test_e2e_subagent_skips_complete_blocks_then_eventually_releases(server_with_pipeline):
    """Subagent makes a tool call (becomes 'known'), then tries to terminate
    without calling complete or need — hook blocks. After the nudge it
    eventually completes and the hook allows.

    A subagent that makes ZERO calls is unenforceable (we can't tell it's
    one of ours); that case is documented in test_hook_for_unknown_session_fails_open.
    """
    srv, Classify, Draft, Pipeline = server_with_pipeline

    dispatch = srv._handle_start_process({"process": "Pipeline", "input": "hi"})
    exec_id = next(iter(srv.runtime.get_run(dispatch["run_id"]).pending_executions))

    # Subagent makes a tool call → session becomes known to us.
    srv._handle_call_tool({
        "execution_id": exec_id,
        "name": "lookup_history",
        "arguments": {"customer_id": "c1"},
        "_parent_session_id": "parent-main",
    })

    # Now tries to terminate without complete. Hook blocks because
    # we KNOW this is our subagent and the queue is empty.
    block = _hook_fires(srv, "parent-main")
    assert block["decision"] == "block"

    # Subagent recovers, calls complete.
    srv._handle_complete({
        "execution_id": exec_id,
        "output": "billing",
        "_parent_session_id": "parent-main",
    })
    assert _hook_fires(srv, "parent-main") == {}


def test_e2e_need_surfaces_needs_resolution_then_abort_fails_run(server_with_pipeline):
    """Phase 2 slice 04: need() routes to main via needs_resolution.
    Main thread can either resolve or abort; this test chooses abort."""
    srv, Classify, Draft, Pipeline = server_with_pipeline

    dispatch = srv._handle_start_process({"process": "Pipeline", "input": "ambiguous"})

    sub = MockSubagent(srv)
    sub.run(
        dispatch,
        plan=[("need", lambda s: {"execution_id": s.execution_id, "reason": "no customer_id"})],
    )

    # SubagentStop after need: hook still allows because need flagged completed.
    assert _hook_fires(srv, "parent-main") == {}

    # Main relays back; runtime surfaces needs_resolution (not failure).
    result = srv._handle_step_complete({"run_id": dispatch["run_id"], "result": None})
    assert result["action"] == "needs_resolution"
    assert "no customer_id" in result["reason"]

    # Main chooses to abort.
    srv._handle_abort_run({"run_id": dispatch["run_id"]})
    status = srv._handle_run_status({"run_id": dispatch["run_id"]})
    assert status["status"] == "aborted"


def test_e2e_subagent_calling_undeclared_tool_surfaces_protocol_error(server_with_pipeline):
    srv, Classify, Draft, Pipeline = server_with_pipeline

    # Register an unrelated tool that no Op declares.
    Tool(name="rogue_tool", description="not declared by any Op", handler=lambda: "nope")

    dispatch = srv._handle_start_process({"process": "Pipeline", "input": "hi"})

    sub = MockSubagent(srv)
    # Drive call_tool through the full _dispatch_tool_call path so we
    # observe the structured error response (not just a raised exception).
    exec_id = next(iter(srv.runtime.get_run(dispatch["run_id"]).pending_executions))
    response = srv._dispatch_tool_call(
        "call_tool",
        {"execution_id": exec_id, "name": "rogue_tool", "arguments": {}},
    )
    import json
    payload = json.loads(response[0].text)
    assert "error" in payload
    assert "did not declare" in payload["error"]


def test_e2e_full_run_writes_zero_extra_mcp_tools(server_with_pipeline):
    """Architectural invariant: an Op library with N tools adds 0 MCP tools."""
    from clops.runtime.mcp_server import ALL_TOOL_NAMES
    srv, *_ = server_with_pipeline
    catalog = srv._build_tool_catalog()
    # Catalog size matches the framework's fixed surface — library size
    # doesn't widen it.
    assert len(catalog) == len(ALL_TOOL_NAMES)
    assert "lookup_history" not in {t.name for t in catalog}


# ---- branch_on E2E narrative ----------------------------------------


def test_e2e_branch_on_routes_only_matched_arm():
    """Full process narrative through branch_on: triage emits a category,
    branch routes, only the matched arm dispatches, run completes."""
    from clops import branch_on

    class Msg(Concept):
        description = "an incoming msg"

    class Cat(Concept):
        description = "a category label"

    class Reply(Concept):
        description = "a reply"

    class Triage(Op):
        Input = Msg
        Output = Cat
        Intent = "Categorize."
        Meta = "Test fixture Op for validating E2E branch_on."

    class HandleBilling(Op):
        Input = Cat
        Output = Reply
        Intent = "Billing handler."
        Meta = "Test fixture Op for validating E2E branch_on."

    class HandleTech(Op):
        Input = Cat
        Output = Reply
        Intent = "Tech handler."
        Meta = "Test fixture Op for validating E2E branch_on."

    def _key(triage_output):
        return "billing" if "billing" in str(triage_output).lower() else "technical"

    class Route(Op):
        Input = Msg
        Output = Reply
        Intent = "Triage then route."
        Meta = "Test fixture Op for validating E2E branch_on."
        body = sequence(
            Triage,
            branch_on(key=_key, arms={"billing": HandleBilling, "technical": HandleTech}),
        )
        entry = True

    srv = FlowServer(ServerConfig())

    d = srv._handle_start_process({"process": "Route", "input": "I was double charged"})
    assert d["agent_config"]["description"].startswith("Execute Triage")
    run_id = d["run_id"]

    # Triage subagent runs; emits "billing".
    sub1 = MockSubagent(srv)
    sub1.run(d, plan=[("complete", lambda s: {"execution_id": s.execution_id, "output": "billing"})])
    assert _hook_fires(srv, "parent-main") == {}

    d2 = srv._handle_step_complete({"run_id": run_id, "result": "billing"})
    assert d2["action"] == "dispatch"
    assert d2["agent_config"]["description"].startswith("Execute HandleBilling")

    sub2 = MockSubagent(srv)
    sub2.run(d2, plan=[("complete", lambda s: {"execution_id": s.execution_id, "output": "refund issued"})])
    assert _hook_fires(srv, "parent-main") == {}

    done = srv._handle_step_complete({"run_id": run_id, "result": "refund issued"})
    assert done["action"] == "done"
    assert done["output"] == "refund issued"

    # Critical: HandleTech was never dispatched.
    op_names = sorted(e.op_name for e in srv.runtime.get_run(run_id).executions.values())
    assert op_names == ["HandleBilling", "Triage"]


# ---- loop E2E narrative ---------------------------------------------


def test_e2e_loop_iterates_until_predicate_satisfied():
    """Refine-until-good narrative: Seed → Refine xN → predicate satisfied → done."""
    from clops import loop

    class Mx(Concept):
        description = "msg"

    class Rx(Concept):
        description = "draft"

    class Seed(Op):
        Input = Mx
        Output = Rx
        Intent = "Produce a v0 draft."
        Meta = "Test fixture Op for validating E2E loop."

    class Refine(Op):
        Input = Rx
        Output = Rx
        Intent = "Refine the draft. Append [done] when satisfied."
        Meta = "Test fixture Op for validating E2E loop."

    class Refiner(Op):
        Input = Mx
        Output = Rx
        Intent = "Seed then refine until satisfied."
        Meta = "Test fixture Op for validating E2E loop."
        body = sequence(
            Seed,
            loop(body=Refine, until=lambda d: "[done]" in str(d), max_iterations=5),
        )
        entry = True

    srv = FlowServer(ServerConfig())
    d = srv._handle_start_process({"process": "Refiner", "input": "topic"})
    run_id = d["run_id"]

    # Seed
    sub = MockSubagent(srv)
    sub.run(d, plan=[("complete", lambda s: {"execution_id": s.execution_id, "output": "v0"})])
    assert _hook_fires(srv, "parent-main") == {}
    d = srv._handle_step_complete({"run_id": run_id, "result": "v0"})

    # Refine iteration 1
    assert d["agent_config"]["description"].startswith("Execute Refine")
    sub = MockSubagent(srv)
    sub.run(d, plan=[("complete", lambda s: {"execution_id": s.execution_id, "output": "v1"})])
    assert _hook_fires(srv, "parent-main") == {}
    d = srv._handle_step_complete({"run_id": run_id, "result": "v1"})

    # Refine iteration 2 — agent appends [done]
    assert d["agent_config"]["description"].startswith("Execute Refine")
    sub = MockSubagent(srv)
    sub.run(d, plan=[("complete", lambda s: {"execution_id": s.execution_id, "output": "v2 [done]"})])
    assert _hook_fires(srv, "parent-main") == {}
    done = srv._handle_step_complete({"run_id": run_id, "result": "v2 [done]"})

    assert done["action"] == "done"
    assert done["output"] == "v2 [done]"

    # Three executions total: 1 Seed, 2 Refines
    counts = {}
    for e in srv.runtime.get_run(run_id).executions.values():
        counts[e.op_name] = counts.get(e.op_name, 0) + 1
    assert counts == {"Seed": 1, "Refine": 2}


# ---- need resolution E2E narrative ----------------------------------


def test_e2e_need_resolve_completes_run():
    """Full narrative: subagent needs → main resolves → subagent completes → done."""

    class Request(Concept):
        description = "A support request. Needs a customer_id to process."

    class Decision(Concept):
        description = "A triage decision."

    class Triage(Op):
        Input = Request
        Output = Decision
        Intent = (
            "Triage the request. If customer_id is missing, call need with "
            "reason 'missing customer_id'. Otherwise output a decision."
        )
        Meta = "Test fixture Op for validating E2E need resolution."
        entry = True

    srv = FlowServer(ServerConfig())
    d = srv._handle_start_process({"process": "Triage", "input": {"message": "help"}})
    run_id = d["run_id"]
    exec_id = next(iter(srv.runtime.get_run(run_id).pending_executions))

    # First subagent needs
    srv._handle_need({
        "execution_id": exec_id,
        "reason": "missing customer_id",
        "_parent_session_id": "parent-main",
    })
    assert _hook_fires(srv, "parent-main") == {}

    # Main thread sees needs_resolution
    result = srv._handle_step_complete({"run_id": run_id, "result": None})
    assert result["action"] == "needs_resolution"
    assert result["execution_id"] == exec_id
    assert result["reason"] == "missing customer_id"

    # Main thread resolves with supplemental
    redispatch = srv._handle_resolve_need({
        "run_id": run_id,
        "execution_id": exec_id,
        "supplemental_input": {"customer_id": "cust_42"},
    })
    assert redispatch["action"] == "dispatch"
    assert "Supplemental input" in redispatch["agent_config"]["prompt"]
    assert "cust_42" in redispatch["agent_config"]["prompt"]

    # Re-dispatched subagent completes normally
    sub = MockSubagent(srv)
    sub.run(redispatch, plan=[("complete", lambda s: {"execution_id": s.execution_id, "output": "Route to billing."})])
    assert _hook_fires(srv, "parent-main") == {}

    done = srv._handle_step_complete({"run_id": run_id, "result": "Route to billing."})
    assert done["action"] == "done"
    assert done["output"] == "Route to billing."

    # State graph: single execution with attempts=2
    executions = list(srv.runtime.get_run(run_id).executions.values())
    assert len(executions) == 1
    assert executions[0].attempts == 2
    assert executions[0].need_resolved is True


# ---- gather parallel E2E narrative ----------------------------------


def test_e2e_gather_dispatches_all_branches_and_synthesizes():
    """Full narrative through gather: Seed → parallel(A, B, C) → Synth → done.
    Verifies the dispatch_parallel payload shape, that all three branches
    appear as OpExecutions, and that Synth's input is the list of three
    outputs in declaration order.
    """
    from clops import gather

    class Mx(Concept):
        description = "a"

    class Rx(Concept):
        description = "b"

    class Seed(Op):
        Input = Mx
        Output = Rx
        Intent = "seed"
        Meta = "Test fixture Op for validating E2E gather."

    class A(Op):
        Input = Rx
        Output = Rx
        Intent = "a"
        Meta = "Test fixture Op for validating E2E gather."

    class B(Op):
        Input = Rx
        Output = Rx
        Intent = "b"
        Meta = "Test fixture Op for validating E2E gather."

    class C(Op):
        Input = Rx
        Output = Rx
        Intent = "c"
        Meta = "Test fixture Op for validating E2E gather."

    class Synth(Op):
        Input = Rx
        Output = Rx
        Intent = "merge"
        Meta = "Test fixture Op for validating E2E gather."

    class Research(Op):
        Input = Mx
        Output = Rx
        Intent = "Research from three angles then synthesize."
        Meta = "Test fixture Op for validating E2E gather."
        body = sequence(Seed, gather(A, B, C), Synth)
        entry = True

    srv = FlowServer(ServerConfig())
    d = srv._handle_start_process({"process": "Research", "input": "topic"})
    run_id = d["run_id"]

    # Seed
    sub = MockSubagent(srv)
    sub.run(d, plan=[("complete", lambda s: {"execution_id": s.execution_id, "output": "seed-out"})])
    assert _hook_fires(srv, "parent-main") == {}

    # Gather → dispatch_parallel
    parallel = srv._handle_step_complete({"run_id": run_id, "result": "seed-out"})
    assert parallel["action"] == "dispatch_parallel"
    assert parallel["report_via"] == "step_complete_parallel"
    exec_ids = parallel["execution_ids"]
    configs = parallel["agent_configs"]
    assert len(exec_ids) == 3
    assert len(configs) == 3

    # Each of the three subagents completes in its own "session" (same
    # parent_session_id here for simplicity, simulating the main thread
    # issuing three parallel Agent calls within one Claude Code session).
    # The complete() calls are routed through the MCP handler so the hook
    # queue gets populated.
    outputs = {}
    for eid, cfg in zip(exec_ids, configs):
        # Pretend a subagent ran: extract execution_id from prompt, call complete.
        import re
        m = re.search(r'execution_id="(exec_[a-f0-9]+)"', cfg["prompt"])
        assert m and m.group(1) == eid
        srv._handle_complete({"execution_id": eid, "output": f"{cfg['description']}:output", "_parent_session_id": "parent-main"})
        outputs[eid] = f"{cfg['description']}:output"

    # Three hook fires (one per stopping subagent) → all release.
    assert _hook_fires(srv, "parent-main") == {}
    assert _hook_fires(srv, "parent-main") == {}
    assert _hook_fires(srv, "parent-main") == {}
    # Fourth hook fires → nothing to release → block (safety).
    assert _hook_fires(srv, "parent-main")["decision"] == "block"

    # Main thread relays all three results.
    d2 = srv._handle_step_complete_parallel({"run_id": run_id, "results": outputs})
    assert d2["action"] == "dispatch"
    assert d2["agent_config"]["description"].startswith("Execute Synth")
    # Synth's prompt carries the list in order.
    prompt = d2["agent_config"]["prompt"]
    # Ordered — declaration order is A, B, C
    a_idx = prompt.index("Execute A for")
    b_idx = prompt.index("Execute B for")
    c_idx = prompt.index("Execute C for")
    assert a_idx < b_idx < c_idx

    # Synth finishes
    sub = MockSubagent(srv)
    sub.run(d2, plan=[("complete", lambda s: {"execution_id": s.execution_id, "output": "merged"})])
    assert _hook_fires(srv, "parent-main") == {}

    done = srv._handle_step_complete({"run_id": run_id, "result": "merged"})
    assert done["action"] == "done"
    assert done["output"] == "merged"

    # State graph has all five.
    counts = {}
    for e in srv.runtime.get_run(run_id).executions.values():
        counts[e.op_name] = counts.get(e.op_name, 0) + 1
    assert counts == {"Seed": 1, "A": 1, "B": 1, "C": 1, "Synth": 1}


def test_e2e_gather_with_composite_branches_runs_batched_rounds():
    """Issue #3 at integration level: a gather of two composite tracks runs as
    batched dispatch_parallel rounds through the real server handlers.

    Seed → gather(TrackA=seq(A1,A2), TrackB=seq(B1)). Round 1 dispatches [A1, B1];
    once B1 finishes, round 2 dispatches just [A2]; outputs join in declaration
    order.
    """
    from clops import gather

    class Mx(Concept):
        description = "a"

    class Rx(Concept):
        description = "b"

    class Seed(Op):
        Input = Mx
        Output = Rx
        Intent = "seed"
        Meta = "Test fixture Op for validating E2E composite gather."

    class A1(Op):
        Input = Rx
        Output = Rx
        Intent = "a1"
        Meta = "Test fixture Op for validating E2E composite gather."

    class A2(Op):
        Input = Rx
        Output = Rx
        Intent = "a2"
        Meta = "Test fixture Op for validating E2E composite gather."

    class B1(Op):
        Input = Rx
        Output = Rx
        Intent = "b1"
        Meta = "Test fixture Op for validating E2E composite gather."

    class TrackA(Op):
        Input = Rx
        Output = Rx
        Intent = "Track A."
        Meta = "Test fixture composition for E2E composite gather."
        body = sequence(A1, A2)

    class TrackB(Op):
        Input = Rx
        Output = Rx
        Intent = "Track B."
        Meta = "Test fixture composition for E2E composite gather."
        body = sequence(B1)

    class Research(Op):
        Input = Mx
        Output = Rx
        Intent = "Two parallel tracks."
        Meta = "Test fixture Op for validating E2E composite gather."
        body = sequence(Seed, gather(TrackA, TrackB))
        entry = True

    srv = FlowServer(ServerConfig())
    d = srv._handle_start_process({"process": "Research", "input": "topic"})
    run_id = d["run_id"]

    sub = MockSubagent(srv)
    sub.run(d, plan=[("complete", lambda s: {"execution_id": s.execution_id, "output": "seed-out"})])

    # Round 1: each track's first leaf, in declaration order.
    r1 = srv._handle_step_complete({"run_id": run_id, "result": "seed-out"})
    assert r1["action"] == "dispatch_parallel"
    ids1 = r1["execution_ids"]
    assert len(ids1) == 2
    assert r1["agent_configs"][0]["description"].startswith("Execute A1")
    assert r1["agent_configs"][1]["description"].startswith("Execute B1")
    srv._handle_complete({"execution_id": ids1[0], "output": "a1-out", "_parent_session_id": "parent-main"})
    srv._handle_complete({"execution_id": ids1[1], "output": "b1-out", "_parent_session_id": "parent-main"})

    # Round 2: TrackB done; TrackA advances to A2 — a 1-leaf parallel round.
    r2 = srv._handle_step_complete_parallel({"run_id": run_id, "results": {ids1[0]: "a1-out", ids1[1]: "b1-out"}})
    assert r2["action"] == "dispatch_parallel"
    assert len(r2["execution_ids"]) == 1
    assert r2["agent_configs"][0]["description"].startswith("Execute A2")
    ids2 = r2["execution_ids"]
    srv._handle_complete({"execution_id": ids2[0], "output": "a2-out", "_parent_session_id": "parent-main"})

    # Join → run done; output is [TrackA, TrackB] in declaration order.
    done = srv._handle_step_complete_parallel({"run_id": run_id, "results": {ids2[0]: "a2-out"}})
    assert done["action"] == "done"
    assert done["output"] == ["a2-out", "b1-out"]

    counts = {}
    for e in srv.runtime.get_run(run_id).executions.values():
        counts[e.op_name] = counts.get(e.op_name, 0) + 1
    assert counts == {"Seed": 1, "A1": 1, "A2": 1, "B1": 1}


def test_e2e_gather_branch_calls_subroutine_through_server():
    """Slice 3 at integration level: a gather branch makes a dynamic sub-Op
    call (call_tool) through the real server handlers, while its peer branch
    completes normally. The calling branch is parked through the subroutine
    cycle; the join still preserves declaration order.

    Seed → gather(Caller[Tools=Sub], Plain). The Caller branch calls Sub
    mid-turn; Plain completes immediately. Subsequent parallel rounds dispatch
    Sub, then re-dispatch Caller with the result, then join [Caller, Plain].
    """
    from clops import gather

    class Mx(Concept):
        description = "a"

    class Rx(Concept):
        description = "b"

    class Seed(Op):
        Input = Mx
        Output = Rx
        Intent = "seed"
        Meta = "Test fixture Op for validating E2E gather-subroutine."

    class Sub(Op):
        Input = Rx
        Output = Rx
        Intent = "define the term"
        Meta = "Test fixture leaf sub-Op for validating E2E gather-subroutine."

    class Caller(Op):
        Input = Rx
        Output = Rx
        Intent = "analyze, defining the key term via the Sub capability"
        Meta = "Test fixture gather branch that makes a dynamic call."
        Tools = [Sub]

    class Plain(Op):
        Input = Rx
        Output = Rx
        Intent = "analyze plainly"
        Meta = "Test fixture peer gather branch (no subroutine)."

    class Research(Op):
        Input = Mx
        Output = Rx
        Intent = "Two parallel branches, one of which calls a sub-Op."
        Meta = "Test fixture Op for validating E2E gather-subroutine."
        body = sequence(Seed, gather(Caller, Plain))
        entry = True

    srv = FlowServer(ServerConfig())
    d = srv._handle_start_process({"process": "Research", "input": "topic"})
    run_id = d["run_id"]

    sub = MockSubagent(srv)
    sub.run(d, plan=[("complete", lambda s: {"execution_id": s.execution_id, "output": "seed-out"})])

    # Round 1: both branches dispatch in declaration order. Caller's prompt
    # advertises the Sub capability.
    r1 = srv._handle_step_complete({"run_id": run_id, "result": "seed-out"})
    assert r1["action"] == "dispatch_parallel"
    caller_id, plain_id = r1["execution_ids"]
    assert r1["agent_configs"][0]["description"].startswith("Execute Caller")
    assert "`Sub`" in r1["agent_configs"][0]["prompt"]

    # The Caller branch makes a dynamic call (routed through _handle_call_tool,
    # which resolves Sub to an Op and calls call_op); the Plain branch completes.
    called = srv._handle_call_tool({
        "execution_id": caller_id,
        "name": "Sub",
        "arguments": {"term": "fiber-optic"},
        "_parent_session_id": "parent-main",
    })
    assert called["ok"] is True
    srv._handle_complete({"execution_id": caller_id, "output": "interim", "_parent_session_id": "parent-main"})
    srv._handle_complete({"execution_id": plain_id, "output": "plain-out", "_parent_session_id": "parent-main"})

    # Round 2: still mid-gather. Sub is dispatched as its own parallel round;
    # its prompt carries only the call arguments, not Caller's context.
    r2 = srv._handle_step_complete_parallel({"run_id": run_id, "results": {caller_id: "interim", plain_id: "plain-out"}})
    assert r2["action"] == "dispatch_parallel"
    assert r2["report_via"] == "step_complete_parallel"
    assert len(r2["execution_ids"]) == 1
    sub_id = r2["execution_ids"][0]
    assert r2["agent_configs"][0]["description"].startswith("Execute Sub")
    assert "fiber-optic" in r2["agent_configs"][0]["prompt"]
    assert "analyze, defining" not in r2["agent_configs"][0]["prompt"]  # clean boundary

    srv._handle_complete({"execution_id": sub_id, "output": "a fiber-optic line is glass", "_parent_session_id": "parent-main"})

    # Round 3: Caller re-dispatched (same execution id) with the Sub result.
    r3 = srv._handle_step_complete_parallel({"run_id": run_id, "results": {sub_id: "a fiber-optic line is glass"}})
    assert r3["action"] == "dispatch_parallel"
    assert r3["execution_ids"] == [caller_id]
    assert "Result from Sub" in r3["agent_configs"][0]["prompt"]
    assert "a fiber-optic line is glass" in r3["agent_configs"][0]["prompt"]

    srv._handle_complete({"execution_id": caller_id, "output": "caller-out", "_parent_session_id": "parent-main"})

    # Join → run done; output is [Caller, Plain] in declaration order.
    done = srv._handle_step_complete_parallel({"run_id": run_id, "results": {caller_id: "caller-out"}})
    assert done["action"] == "done"
    assert done["output"] == ["caller-out", "plain-out"]

    # State graph: one execution per Op (the Caller execution is reused).
    counts = {}
    for e in srv.runtime.get_run(run_id).executions.values():
        counts[e.op_name] = counts.get(e.op_name, 0) + 1
    assert counts == {"Seed": 1, "Caller": 1, "Plain": 1, "Sub": 1}
