"""Tests for Runtime state store integration (Phase 3)."""

from __future__ import annotations

import pytest

from clops import Concept, Op, Store, sequence
from clops.registry import registry
from clops.runtime import Runtime


class Brief(Concept):
    description = "A project brief"


class Result(Concept):
    description = "A result"


class Task(Concept):
    description = "A task"


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


# ---- Start creates StateManager -------------------------------------


def test_start_creates_state_manager():
    class WithStore(Op):
        Input = Brief
        Output = Result
        Intent = "Has stores"
        Meta = "Test."
        entry = True
        tasks = Store(dict[str, Task])

    rt = Runtime()
    d = rt.start("WithStore", "brief", enforce_entry=True)
    sm = rt.get_state_manager(d["run_id"])
    assert sm is not None
    assert "tasks" in sm.stores


def test_start_no_stores_no_state_manager():
    class NoStore(Op):
        Input = Brief
        Output = Result
        Intent = "No stores"
        Meta = "Test."
        entry = True

    rt = Runtime()
    d = rt.start("NoStore", "brief", enforce_entry=True)
    sm = rt.get_state_manager(d["run_id"])
    assert sm is None


def test_start_collects_stores_from_body():
    class StepA(Op):
        Input = Brief
        Output = Result
        Intent = "Step A"
        Meta = "Step A."
        progress = Store(str)

    class StepB(Op):
        Input = Result
        Output = Result
        Intent = "Step B"
        Meta = "Step B."

    class Pipeline(Op):
        Input = Brief
        Output = Result
        Intent = "Pipeline"
        Meta = "Test."
        entry = True
        tasks = Store(dict[str, Task])
        body = sequence(StepA, StepB)

    rt = Runtime()
    d = rt.start("Pipeline", "brief", enforce_entry=True)
    sm = rt.get_state_manager(d["run_id"])
    assert sm is not None
    assert "tasks" in sm.stores
    assert "progress" in sm.stores


def test_collect_stores_type_conflict():
    class A(Op):
        Input = Brief
        Output = Result
        Intent = "A"
        Meta = "A."
        items = Store(dict[str, Task])

    class B(Op):
        Input = Result
        Output = Result
        Intent = "B"
        Meta = "B."
        items = Store(list[str])  # Conflict: dict vs list

    class Bad(Op):
        Input = Brief
        Output = Result
        Intent = "Bad"
        Meta = "Bad."
        entry = True
        body = sequence(A, B)

    rt = Runtime()
    with pytest.raises(Exception, match="type conflict"):
        rt.start("Bad", "brief", enforce_entry=True)


# ---- Runtime.state() ------------------------------------------------


def test_state_get_set_round_trip():
    class Worker(Op):
        Input = Brief
        Output = Result
        Intent = "Work"
        Meta = "Test."
        entry = True
        notes = Store(str)

    rt = Runtime()
    d = rt.start("Worker", "brief", enforce_entry=True)
    exec_id = next(iter(rt.get_run(d["run_id"]).pending_executions))

    rt.state(exec_id, "notes", "set", value="hello")
    assert rt.state(exec_id, "notes", "get") == "hello"


def test_state_dict_operations_via_runtime():
    class Worker2(Op):
        Input = Brief
        Output = Result
        Intent = "Work"
        Meta = "Test."
        entry = True
        tasks = Store(dict[str, Task])

    rt = Runtime()
    d = rt.start("Worker2", "brief", enforce_entry=True)
    exec_id = next(iter(rt.get_run(d["run_id"]).pending_executions))

    rt.state(exec_id, "tasks", "set", id="t1", value={"name": "Review"})
    result = rt.state(exec_id, "tasks", "get", id="t1")
    assert result["name"] == "Review"

    all_tasks = rt.state(exec_id, "tasks", "list")
    assert "t1" in all_tasks


def test_state_unknown_store_raises():
    class Worker3(Op):
        Input = Brief
        Output = Result
        Intent = "Work"
        Meta = "Test."
        entry = True
        notes = Store(str)

    rt = Runtime()
    d = rt.start("Worker3", "brief", enforce_entry=True)
    exec_id = next(iter(rt.get_run(d["run_id"]).pending_executions))

    with pytest.raises(Exception, match="Unknown store"):
        rt.state(exec_id, "nonexistent", "get")


def test_state_unknown_execution_raises():
    rt = Runtime()
    with pytest.raises(Exception):
        rt.state("fake_exec_id", "notes", "get")


def test_state_no_stores_raises():
    class NoStore2(Op):
        Input = Brief
        Output = Result
        Intent = "No stores"
        Meta = "Test."
        entry = True

    rt = Runtime()
    d = rt.start("NoStore2", "brief", enforce_entry=True)
    exec_id = next(iter(rt.get_run(d["run_id"]).pending_executions))

    with pytest.raises(Exception, match="No state stores"):
        rt.state(exec_id, "notes", "get")
