"""Protocol-level tests for the MCP server handler layer.

We exercise the handler methods directly, bypassing stdio. The Layer 2
test pattern per test-plan.md: scripted calls through the handler
surface, verify state transitions and response shapes without LLM
involvement.
"""

import pytest

from clops import Concept, Op, Tool
from clops.runtime.core import RuntimeError_
from clops.runtime.mcp_server import (
    ALL_TOOL_NAMES,
    FlowServer,
    ServerConfig,
)


class M(Concept):
    description = "a message"


class R(Concept):
    description = "a result"


@pytest.fixture
def server_with_ops():
    """A FlowServer wrapping a library with one entry Op and one tool."""

    lookup = Tool(
        name="lookup",
        description="Look up a customer by id.",
        parameters={"customer_id": str},
        handler=lambda customer_id: {"found": customer_id},
    )

    class Echo(Op):
        Input = M
        Output = R
        Intent = "Echo the message back."
        Meta = "Test fixture Op for validating MCP server handlers."
        Tools = [lookup]
        entry = True

    srv = FlowServer(ServerConfig())
    return srv, Echo, lookup


# ---- Tool catalog ----------------------------------------------------


def test_tool_catalog_is_fixed_size_regardless_of_op_tools(server_with_ops):
    srv, *_ = server_with_ops
    catalog = srv._build_tool_catalog()
    names = {t.name for t in catalog}
    assert names == set(ALL_TOOL_NAMES)
    # Critically: no per-Op-tool registration. An Op declaring `lookup`
    # does NOT add a `lookup` MCP tool. Op libraries never grow the
    # MCP tool surface.
    assert "lookup" not in names
    assert len(catalog) == len(ALL_TOOL_NAMES)


def test_tool_catalog_unchanged_when_many_op_tools_are_added():
    for i in range(30):
        Tool(
            name=f"tool_{i}",
            description=f"tool {i}",
            parameters={},
            handler=lambda: None,
        )
    srv = FlowServer(ServerConfig())
    catalog = srv._build_tool_catalog()
    assert len(catalog) == len(ALL_TOOL_NAMES)


# ---- Main-thread tool routing ---------------------------------------


def test_list_processes_returns_entry_tagged_only(server_with_ops):
    srv, Echo, _ = server_with_ops
    result = srv._handle_list_processes({})
    names = [p["name"] for p in result]
    assert names == ["Echo"]


def test_start_process_enforces_entry(server_with_ops):
    srv, _, _ = server_with_ops

    class Internal(Op):
        Input = M
        Output = R
        Intent = "Internal-only."
        Meta = "Test fixture Op for validating entry enforcement."
        # no entry=True

    with pytest.raises(RuntimeError_, match="not an entry point"):
        srv._handle_start_process({"process": "Internal", "input": "x"})


def test_start_process_then_step_complete_flow(server_with_ops):
    srv, Echo, _ = server_with_ops
    dispatch = srv._handle_start_process({"process": "Echo", "input": "hi"})
    assert dispatch["action"] == "dispatch"
    run_id = dispatch["run_id"]

    # Subagent signals complete.
    exec_id = next(iter(srv.runtime.get_run(run_id).pending_executions))
    srv._handle_complete({"execution_id": exec_id, "output": "hi back"})

    done = srv._handle_step_complete({"run_id": run_id, "result": "hi back"})
    assert done["action"] == "done"
    assert done["output"] == "hi back"


def test_run_status_and_abort(server_with_ops):
    srv, Echo, _ = server_with_ops
    d = srv._handle_start_process({"process": "Echo", "input": "hi"})
    status = srv._handle_run_status({"run_id": d["run_id"]})
    assert status["status"] == "running"

    aborted = srv._handle_abort_run({"run_id": d["run_id"]})
    assert aborted["status"] == "aborted"


# ---- Subagent tool routing: call_tool dispatch ----------------------


def test_call_tool_routes_to_op_declared_tool(server_with_ops):
    srv, Echo, lookup = server_with_ops
    d = srv._handle_start_process({"process": "Echo", "input": "hi"})
    exec_id = next(iter(srv.runtime.get_run(d["run_id"]).pending_executions))

    result = srv._handle_call_tool({
        "execution_id": exec_id,
        "name": "lookup",
        "arguments": {"customer_id": "c_1"},
    })
    assert result == {"found": "c_1"}


def test_call_tool_rejects_undeclared_tool(server_with_ops):
    srv, Echo, lookup = server_with_ops
    # Register an extra tool that Echo did NOT declare.
    extra = Tool(name="other", description="other tool", handler=lambda: "nope")

    d = srv._handle_start_process({"process": "Echo", "input": "hi"})
    exec_id = next(iter(srv.runtime.get_run(d["run_id"]).pending_executions))

    with pytest.raises(RuntimeError_, match="did not declare"):
        srv._handle_call_tool({
            "execution_id": exec_id,
            "name": "other",
            "arguments": {},
        })


def test_call_tool_with_unknown_name_errors(server_with_ops):
    srv, Echo, lookup = server_with_ops
    d = srv._handle_start_process({"process": "Echo", "input": "hi"})
    exec_id = next(iter(srv.runtime.get_run(d["run_id"]).pending_executions))

    with pytest.raises(RuntimeError_, match="did not declare"):
        srv._handle_call_tool({
            "execution_id": exec_id,
            "name": "ghost",
            "arguments": {},
        })


def test_call_tool_with_unknown_execution_errors(server_with_ops):
    srv, *_ = server_with_ops
    with pytest.raises(RuntimeError_, match="not found"):
        srv._handle_call_tool({
            "execution_id": "exec_ghost",
            "name": "lookup",
            "arguments": {},
        })


# ---- Library-import error surfacing ---------------------------------


def test_library_import_failure_is_held_and_surfaced():
    srv = FlowServer(ServerConfig(libraries=["definitely_not_a_real_package"]))
    srv.load_library_safe()
    # Held error should appear on the next main-thread dispatch.
    result = srv._dispatch_tool_call("list_processes", {})
    # _dispatch_tool_call returns list[TextContent]; decode the payload.
    import json
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "definitely_not_a_real_package" in payload["error"]


# ---- Recursive library import ----------------------------------------


def test_load_library_imports_submodules_recursively(tmp_path, monkeypatch):
    """Op classes register on import. A submodule the library's
    __init__.py forgot to pull in must still be discovered, so
    file-presence is enough — same convention `clops show` uses.
    """
    import sys

    from clops.registry import registry
    from clops.runtime.mcp_server import load_library

    pkg_name = "_clops_recursive_load_test_pkg"
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("# Intentionally does NOT import sub.\n")
    (pkg_dir / "sub.py").write_text(
        "from clops import Concept, Field, Op\n"
        "class _In(Concept):\n"
        "    description = 'in'\n"
        "    x = Field('x')\n"
        "class _Out(Concept):\n"
        "    description = 'out'\n"
        "    y = Field('y')\n"
        "class DeepEntry(Op):\n"
        "    Input = _In\n"
        "    Output = _Out\n"
        "    Intent = 'entry op in a submodule that __init__ does not import'\n"
        "    Meta = 'Test fixture: lives in a submodule the package __init__ does not import; load_library must still discover it.'\n"
        "    entry = True\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    # Cleanup: drop both the pkg and submodule from sys.modules after the test
    # so re-runs and unrelated tests get a clean slate.
    for name in (pkg_name, f"{pkg_name}.sub"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    load_library(pkg_name)

    assert "DeepEntry" in registry.ops()


# ---- Hook queue integration (via server.runtime) --------------------


def test_complete_queues_for_hook_release(server_with_ops):
    srv, Echo, _ = server_with_ops
    d = srv._handle_start_process({"process": "Echo", "input": "hi"})
    exec_id = next(iter(srv.runtime.get_run(d["run_id"]).pending_executions))
    srv._handle_complete({
        "execution_id": exec_id,
        "output": "x",
        "_parent_session_id": "parent-1",
    })
    # Hook-side release consumes from the queue.
    assert srv.runtime.release_one_completed("parent-1") == exec_id
    assert srv.runtime.release_one_completed("parent-1") is None
