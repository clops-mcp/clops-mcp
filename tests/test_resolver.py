"""Tests for Resolve — pre-computed state queries (Phase 7)."""

from __future__ import annotations

import json

from clops.runtime.resolver import ResolvedItem, render_resolved_for_prompt, resolve
from clops.runtime.state_manager import StateManager


def make_sm_with_tasks() -> StateManager:
    sm = StateManager("run-test")
    sm.register_store("tasks", "dict")
    sm.execute("tasks", "set", id="t1", value={"name": "Review", "status": "pending"})
    sm.execute("tasks", "set", id="t2", value={"name": "Fix bug", "status": "done"})
    return sm


# ---- resolve() -------------------------------------------------------


def test_resolve_simple_get():
    sm = make_sm_with_tasks()
    spec = {
        "current_task": {
            "store": "tasks",
            "op": "get",
            "bind": {"id": "input.task_id"},
        },
    }
    items = resolve(spec, sm, {"task_id": "t1"})
    assert len(items) == 1
    assert items[0].name == "current_task"
    assert items[0].value["name"] == "Review"
    assert items[0].source_store == "tasks"
    assert items[0].bound_kwargs == {"id": "t1"}


def test_resolve_string_input():
    """Input can be a JSON string, not just a dict."""
    sm = make_sm_with_tasks()
    spec = {
        "current_task": {
            "store": "tasks",
            "op": "get",
            "bind": {"id": "input.task_id"},
        },
    }
    items = resolve(spec, sm, json.dumps({"task_id": "t2"}))
    assert items[0].value["name"] == "Fix bug"


def test_resolve_missing_input_field():
    sm = make_sm_with_tasks()
    spec = {
        "current_task": {
            "store": "tasks",
            "op": "get",
            "bind": {"id": "input.nonexistent"},
        },
    }
    items = resolve(spec, sm, {"task_id": "t1"})
    assert items[0].value is None


def test_resolve_list_op():
    sm = make_sm_with_tasks()
    spec = {
        "all_tasks": {
            "store": "tasks",
            "op": "list",
        },
    }
    items = resolve(spec, sm, {})
    assert len(items) == 1
    assert "t1" in items[0].value
    assert "t2" in items[0].value


def test_resolve_unknown_store():
    sm = make_sm_with_tasks()
    spec = {
        "nope": {
            "store": "nonexistent",
            "op": "get",
            "bind": {"id": "input.x"},
        },
    }
    items = resolve(spec, sm, {"x": "1"})
    assert items[0].value is None


# ---- render_resolved_for_prompt() ------------------------------------


def test_render_resolved_shows_values():
    items = [
        ResolvedItem(
            name="current_task",
            value={"name": "Review", "status": "pending"},
            source_store="tasks",
            source_op="get",
            bound_kwargs={"id": "t1"},
        ),
    ]
    rendered = render_resolved_for_prompt(items)
    assert "current_task" in rendered
    assert "Review" in rendered


def test_render_resolved_scoped_operations():
    items = [
        ResolvedItem(
            name="current_task",
            value={"name": "Review"},
            source_store="tasks",
            source_op="get",
            bound_kwargs={"id": "t1"},
        ),
    ]
    rendered = render_resolved_for_prompt(items)
    assert "current_task.update(value)" in rendered
    assert "current_task.delete()" in rendered


def test_render_resolved_no_scoped_ops_for_list():
    items = [
        ResolvedItem(
            name="all_tasks",
            value={"t1": {}, "t2": {}},
            source_store="tasks",
            source_op="list",
            bound_kwargs={},
        ),
    ]
    rendered = render_resolved_for_prompt(items)
    assert "update" not in rendered
    assert "delete" not in rendered


def test_render_resolved_empty():
    assert render_resolved_for_prompt([]) == ""


# ---- Scoped operations (alias routing) -------------------------------


def test_scoped_update_via_alias():
    sm = make_sm_with_tasks()
    sm.register_resolved("exec-1", "current_task", "tasks", {"id": "t1"})
    # Update via alias.
    sm.execute("current_task", "update", execution_id="exec-1",
               value={"name": "Review DONE", "status": "done"})
    # Verify the underlying store was updated.
    result = sm.execute("tasks", "get", id="t1")
    assert result["name"] == "Review DONE"
    assert result["status"] == "done"


def test_scoped_delete_via_alias():
    sm = make_sm_with_tasks()
    sm.register_resolved("exec-1", "current_task", "tasks", {"id": "t1"})
    sm.execute("current_task", "delete", execution_id="exec-1")
    assert sm.execute("tasks", "get", id="t1") is None


def test_scoped_get_via_alias():
    sm = make_sm_with_tasks()
    sm.register_resolved("exec-1", "current_task", "tasks", {"id": "t1"})
    result = sm.execute("current_task", "get", execution_id="exec-1")
    assert result["name"] == "Review"


def test_scoped_alias_unknown_without_execution_id():
    sm = make_sm_with_tasks()
    sm.register_resolved("exec-1", "current_task", "tasks", {"id": "t1"})
    # Without execution_id, alias isn't found → error.
    import pytest
    with pytest.raises(ValueError, match="Unknown store"):
        sm.execute("current_task", "get")
