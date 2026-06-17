"""Tests for custom queries via Store subclasses (Phase 8)."""

from __future__ import annotations

from tinydb import where

from clops import Concept, Op, Store
from clops.registry import registry
from clops.runtime import Runtime

import pytest


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


# ---- Static queries (queries dict) -----------------------------------


class TaskStore(Store):
    type_hint = dict[str, Task]
    queries = {
        "pending": where("status") == "pending",
        "done": where("status") == "done",
    }


def test_custom_query_static_registered():
    store = TaskStore()
    assert "pending" in store._static_queries
    assert "done" in store._static_queries


def test_custom_query_static_executes():
    class WithTaskStore(Op):
        Input = Brief
        Output = Result
        Intent = "Work"
        Meta = "Test."
        entry = True
        tasks = TaskStore()

    rt = Runtime()
    d = rt.start("WithTaskStore", "brief", enforce_entry=True)
    exec_id = next(iter(rt.get_run(d["run_id"]).pending_executions))

    rt.state(exec_id, "tasks", "set", id="t1", value={"name": "A", "status": "pending"})
    rt.state(exec_id, "tasks", "set", id="t2", value={"name": "B", "status": "done"})
    rt.state(exec_id, "tasks", "set", id="t3", value={"name": "C", "status": "pending"})

    pending = rt.state(exec_id, "tasks", "pending")
    assert len(pending) == 2
    names = {r["name"] for r in pending}
    assert names == {"A", "C"}

    done = rt.state(exec_id, "tasks", "done")
    assert len(done) == 1
    assert done[0]["name"] == "B"


# ---- Method-based queries (parameterized) ----------------------------


class AssignableTaskStore(Store):
    type_hint = dict[str, Task]
    queries = {
        "pending": where("status") == "pending",
    }

    def by_assignee(self, table, assignee: str):
        """Tasks assigned to a specific agent."""
        return table.search(where("assignee") == assignee)


def test_custom_query_method_registered():
    store = AssignableTaskStore()
    assert "by_assignee" in store._custom_methods


def test_custom_query_method_executes():
    class WithAssignableStore(Op):
        Input = Brief
        Output = Result
        Intent = "Work"
        Meta = "Test."
        entry = True
        tasks = AssignableTaskStore()

    rt = Runtime()
    d = rt.start("WithAssignableStore", "brief", enforce_entry=True)
    exec_id = next(iter(rt.get_run(d["run_id"]).pending_executions))

    rt.state(exec_id, "tasks", "set", id="t1", value={"name": "A", "assignee": "alice"})
    rt.state(exec_id, "tasks", "set", id="t2", value={"name": "B", "assignee": "bob"})
    rt.state(exec_id, "tasks", "set", id="t3", value={"name": "C", "assignee": "alice"})

    alice_tasks = rt.state(exec_id, "tasks", "by_assignee", assignee="alice")
    assert len(alice_tasks) == 2
    names = {r["name"] for r in alice_tasks}
    assert names == {"A", "C"}


# ---- Prompt rendering ------------------------------------------------


def test_custom_query_in_prompt():
    store = AssignableTaskStore()
    store.name = "tasks"

    from clops.runtime.state_manager import StateManager

    sm = StateManager("run-test")
    sm.register_store(
        "tasks", "dict",
        custom_queries=store._static_queries,
        custom_methods={
            k: lambda table, _m=m, _s=store, **kw: _m(_s, table, **kw)
            for k, m in store._custom_methods.items()
        },
    )
    rendered = sm.render_operations_for_prompt()
    assert "tasks.pending()" in rendered
    assert "tasks.by_assignee(...)" in rendered


def test_custom_query_names():
    store = AssignableTaskStore()
    names = store.custom_query_names()
    assert "pending" in names
    assert "by_assignee" in names
