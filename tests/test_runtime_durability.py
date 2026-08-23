"""Run state outlives the process that drove it.

A run is hours of wall clock and dozens of subagents. When it lived only on
the Runtime object, an `/mcp` reconnect took all of it — silently, and with no
recovery path. These tests pin the durability contract: with a `state_dir`,
the run record and its stores land on disk at every quiescence, a fresh
Runtime reads them back, and the run that cannot be resumed says so.
"""

from __future__ import annotations

import pytest

from clops import Concept, Op, Store, sequence
from clops.registry import registry
from clops.runtime import Runtime
from clops.runtime.core import RuntimeError_
from clops.runtime.state import RunStatus


class Brief(Concept):
    description = "A project brief"


class Result(Concept):
    description = "A result"


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def _two_step_process():
    class First(Op):
        Input = Brief
        Output = Result
        Intent = "First step"
        Meta = "Test fixture."
        findings = Store(list[str])

    class Second(Op):
        Input = Result
        Output = Result
        Intent = "Second step"
        Meta = "Test fixture."

    class Audit(Op):
        Input = Brief
        Output = Result
        Intent = "Two steps"
        Meta = "Test fixture."
        entry = True
        body = sequence(First, Second)

    return Audit


# ---- Persistence -----------------------------------------------------


def test_run_writes_a_state_file(tmp_path):
    _two_step_process()
    rt = Runtime(state_dir=tmp_path)
    run_id = rt.start("Audit", "brief", enforce_entry=True)["run_id"]

    assert (tmp_path / "state" / f"{run_id}.json").exists()


def test_no_state_dir_keeps_everything_in_memory():
    from tinydb.storages import MemoryStorage

    _two_step_process()
    rt = Runtime()
    run_id = rt.start("Audit", "brief", enforce_entry=True)["run_id"]

    sm = rt.get_state_manager(run_id)
    assert isinstance(sm.db.storage, MemoryStorage)


def test_reconnect_recovers_the_run_and_its_stores(tmp_path):
    _two_step_process()
    rt = Runtime(state_dir=tmp_path)
    run_id = rt.start("Audit", "brief", enforce_entry=True)["run_id"]
    exec_id = next(iter(rt.get_run(run_id).pending_executions))

    # The first step does its work and writes it to the store.
    rt.state(exec_id, "findings", "append", value="auth is unguarded")
    rt.complete(exec_id, "step one output")

    # ... and then the MCP server goes away and comes back.
    reconnected = Runtime(state_dir=tmp_path)
    status = reconnected.status(run_id)

    assert status["status"] == RunStatus.INTERRUPTED.value
    assert status["process"] == "Audit"
    assert "interrupted" in status["note"].lower()
    assert [e["output"] for e in status["executions"]] == ["step one output"]

    sm = reconnected.get_state_manager(run_id)
    assert sm.execute("findings", "list") == ["auth is unguarded"]


def test_interrupted_run_cannot_be_advanced(tmp_path):
    _two_step_process()
    rt = Runtime(state_dir=tmp_path)
    run_id = rt.start("Audit", "brief", enforce_entry=True)["run_id"]

    reconnected = Runtime(state_dir=tmp_path)
    with pytest.raises(RuntimeError_, match="cannot be advanced"):
        reconnected.step_complete(run_id, "result")


def test_unknown_run_still_raises(tmp_path):
    rt = Runtime(state_dir=tmp_path)
    with pytest.raises(RuntimeError_, match="Unknown run"):
        rt.status("run_nosuchrun")


def test_terminal_status_survives_recovery(tmp_path):
    class Solo(Op):
        Input = Brief
        Output = Result
        Intent = "One step"
        Meta = "Test fixture."
        entry = True

    rt = Runtime(state_dir=tmp_path)
    run_id = rt.start("Solo", "brief", enforce_entry=True)["run_id"]
    rt.step_complete(run_id, "the answer")

    reconnected = Runtime(state_dir=tmp_path)
    status = reconnected.status(run_id)
    # A run that finished is not "interrupted" — it has nothing left to do.
    assert status["status"] == RunStatus.COMPLETED.value
    assert status["output"] == "the answer"
    assert "note" not in status


def test_aborted_run_stays_aborted(tmp_path):
    _two_step_process()
    rt = Runtime(state_dir=tmp_path)
    run_id = rt.start("Audit", "brief", enforce_entry=True)["run_id"]
    rt.abort(run_id)

    reconnected = Runtime(state_dir=tmp_path)
    assert reconnected.status(run_id)["status"] == RunStatus.ABORTED.value


# ---- Finding a run again ---------------------------------------------


def test_list_runs_finds_persisted_runs(tmp_path):
    _two_step_process()
    rt = Runtime(state_dir=tmp_path)
    first = rt.start("Audit", "brief one", enforce_entry=True)["run_id"]
    second = rt.start("Audit", "brief two", enforce_entry=True)["run_id"]

    reconnected = Runtime(state_dir=tmp_path)
    runs = reconnected.list_runs()

    assert {r["run_id"] for r in runs} == {first, second}
    assert all(r["process"] == "Audit" for r in runs)
    assert all(r["status"] == RunStatus.INTERRUPTED.value for r in runs)
    assert all(r["live"] is False for r in runs)


def test_list_runs_marks_live_runs(tmp_path):
    _two_step_process()
    rt = Runtime(state_dir=tmp_path)
    run_id = rt.start("Audit", "brief", enforce_entry=True)["run_id"]

    runs = rt.list_runs()
    assert [r["run_id"] for r in runs] == [run_id]
    assert runs[0]["live"] is True
    assert runs[0]["status"] == RunStatus.RUNNING.value


def test_list_runs_is_empty_without_a_state_dir():
    assert Runtime().list_runs() == []


# ---- Through the MCP server surface ----------------------------------


def test_server_persists_runs_under_the_project_dir(tmp_path):
    from clops.runtime.mcp_server import FlowServer, ServerConfig

    class Solo(Op):
        Input = Brief
        Output = Result
        Intent = "One step"
        Meta = "Test fixture."
        entry = True

    srv = FlowServer(ServerConfig(project_dir=tmp_path))
    run_id = srv._handle_start_process({"process": "Solo", "input": "brief"})["run_id"]

    assert (tmp_path / ".claude" / ".clops" / "state" / f"{run_id}.json").exists()

    # A second server over the same project — what an /mcp reconnect produces.
    reconnected = FlowServer(ServerConfig(project_dir=tmp_path))
    listed = reconnected._handle_list_runs({})
    assert [r["run_id"] for r in listed] == [run_id]
    assert reconnected._handle_run_status({"run_id": run_id})["process"] == "Solo"


# ---- What run_status carries -----------------------------------------


def test_live_run_status_omits_step_outputs(tmp_path):
    """A running orchestrator already has every step output from
    step_complete; echoing them back would just inflate the payload."""
    _two_step_process()
    rt = Runtime(state_dir=tmp_path)
    run_id = rt.start("Audit", "brief", enforce_entry=True)["run_id"]

    status = rt.status(run_id)
    assert status["status"] == RunStatus.RUNNING.value
    assert all("output" not in e for e in status["executions"])


def test_stopped_run_status_carries_store_contents(tmp_path):
    _two_step_process()
    rt = Runtime(state_dir=tmp_path)
    run_id = rt.start("Audit", "brief", enforce_entry=True)["run_id"]
    exec_id = next(iter(rt.get_run(run_id).pending_executions))
    rt.state(exec_id, "findings", "append", value="auth is unguarded")

    status = Runtime(state_dir=tmp_path).status(run_id)
    assert "auth is unguarded" in status["stores"]["findings"]
