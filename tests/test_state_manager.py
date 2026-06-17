"""Tests for StateManager (Phase 2)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from tinydb import where

from clops.runtime.state_manager import StateManager, StoreData


# ---- Helpers ---------------------------------------------------------


def make_sm() -> StateManager:
    """In-memory StateManager for testing."""
    return StateManager("run-test")


# ---- Scalar operations -----------------------------------------------


def test_scalar_get_set():
    sm = make_sm()
    sm.register_store("notes", "scalar")
    sm.execute("notes", "set", value="hello")
    assert sm.execute("notes", "get") == "hello"


def test_scalar_default_none():
    sm = make_sm()
    sm.register_store("notes", "scalar")
    assert sm.execute("notes", "get") is None


def test_scalar_overwrite():
    sm = make_sm()
    sm.register_store("db", "scalar")
    sm.execute("db", "set", value="staging")
    sm.execute("db", "set", value="production")
    assert sm.execute("db", "get") == "production"


# ---- List operations -------------------------------------------------


def test_list_append_get():
    sm = make_sm()
    sm.register_store("files", "list")
    sm.execute("files", "append", value="a.py")
    sm.execute("files", "append", value="b.py")
    assert sm.execute("files", "get", index=0) == "a.py"
    assert sm.execute("files", "get", index=1) == "b.py"


def test_list_list():
    sm = make_sm()
    sm.register_store("files", "list")
    sm.execute("files", "append", value="a.py")
    sm.execute("files", "append", value="b.py")
    assert sm.execute("files", "list") == ["a.py", "b.py"]


def test_list_remove():
    sm = make_sm()
    sm.register_store("files", "list")
    sm.execute("files", "append", value="a.py")
    sm.execute("files", "append", value="b.py")
    sm.execute("files", "append", value="c.py")
    removed = sm.execute("files", "remove", index=1)
    assert removed == "b.py"
    assert sm.execute("files", "list") == ["a.py", "c.py"]


def test_list_default_empty():
    sm = make_sm()
    sm.register_store("files", "list")
    assert sm.execute("files", "list") == []


def test_list_get_out_of_range():
    sm = make_sm()
    sm.register_store("files", "list")
    with pytest.raises(IndexError):
        sm.execute("files", "get", index=0)


# ---- Dict operations -------------------------------------------------


def test_dict_set_get():
    sm = make_sm()
    sm.register_store("tasks", "dict")
    sm.execute("tasks", "set", id="t1", value={"name": "Review", "status": "pending"})
    result = sm.execute("tasks", "get", id="t1")
    assert result["name"] == "Review"
    assert result["status"] == "pending"


def test_dict_list():
    sm = make_sm()
    sm.register_store("tasks", "dict")
    sm.execute("tasks", "set", id="t1", value={"name": "A"})
    sm.execute("tasks", "set", id="t2", value={"name": "B"})
    data = sm.execute("tasks", "list")
    assert "t1" in data
    assert "t2" in data
    assert data["t1"]["name"] == "A"


def test_dict_add_generates_key():
    sm = make_sm()
    sm.register_store("tasks", "dict")
    key = sm.execute("tasks", "add", value={"name": "New task"})
    assert key.startswith("id_")
    assert sm.execute("tasks", "get", id=key)["name"] == "New task"


def test_dict_delete():
    sm = make_sm()
    sm.register_store("tasks", "dict")
    sm.execute("tasks", "set", id="t1", value={"name": "A"})
    assert sm.execute("tasks", "delete", id="t1") is True
    assert sm.execute("tasks", "get", id="t1") is None


def test_dict_delete_missing():
    sm = make_sm()
    sm.register_store("tasks", "dict")
    assert sm.execute("tasks", "delete", id="nope") is False


def test_dict_default_empty():
    sm = make_sm()
    sm.register_store("tasks", "dict")
    assert sm.execute("tasks", "list") == {}


def test_dict_set_overwrites():
    sm = make_sm()
    sm.register_store("tasks", "dict")
    sm.execute("tasks", "set", id="t1", value={"name": "A"})
    sm.execute("tasks", "set", id="t1", value={"name": "B"})
    assert sm.execute("tasks", "get", id="t1")["name"] == "B"


def test_dict_search_with_tinydb_query():
    sm = make_sm()
    sm.register_store("tasks", "dict")
    sm.execute("tasks", "set", id="t1", value={"name": "A", "status": "pending"})
    sm.execute("tasks", "set", id="t2", value={"name": "B", "status": "done"})
    sm.execute("tasks", "set", id="t3", value={"name": "C", "status": "pending"})
    store = sm.stores["tasks"]
    results = store.execute("search", query=where("status") == "pending")
    assert len(results) == 2
    names = {r["name"] for r in results}
    assert names == {"A", "C"}


def test_dict_scalar_values():
    """Dict stores can hold scalar values, not just dicts."""
    sm = make_sm()
    sm.register_store("config", "dict")
    sm.execute("config", "set", id="db", value="staging")
    assert sm.execute("config", "get", id="db") == "staging"


# ---- Execute routing -------------------------------------------------


def test_execute_unknown_op_raises():
    sm = make_sm()
    sm.register_store("notes", "scalar")
    with pytest.raises(ValueError, match="Unknown operation"):
        sm.execute("notes", "explode")


def test_execute_unknown_store_raises():
    sm = make_sm()
    with pytest.raises(ValueError, match="Unknown store"):
        sm.execute("nope", "get")


# ---- Constants -------------------------------------------------------


def test_constant_rejects_write():
    sm = make_sm()
    sd = sm.register_store("db", "scalar", read_only=True)
    # Pre-populate via internal method (runtime does this at init).
    sd._scalar_set("staging")
    # Writes through execute are rejected.
    with pytest.raises(ValueError, match="read-only"):
        sm.execute("db", "set", value="production")


def test_constant_allows_read():
    sm = make_sm()
    sd = sm.register_store("db", "scalar", read_only=True)
    sd._scalar_set("staging")
    assert sm.execute("db", "get") == "staging"


# ---- Registration ----------------------------------------------------


def test_register_store_idempotent():
    sm = make_sm()
    sm.register_store("tasks", "dict")
    sm.register_store("tasks", "dict")  # same kind, no error
    assert len(sm.stores) == 1


def test_register_store_kind_conflict():
    sm = make_sm()
    sm.register_store("tasks", "dict")
    with pytest.raises(ValueError, match="already registered"):
        sm.register_store("tasks", "list")


# ---- Prompt rendering ------------------------------------------------


def test_render_scalar_inline():
    sm = make_sm()
    sd = sm.register_store("db", "scalar")
    sd._scalar_set("staging")
    rendered = sd.render_for_prompt()
    assert '"staging"' in rendered


def test_render_scalar_truncated():
    sm = make_sm()
    sd = sm.register_store("big", "scalar")
    sd._scalar_set("x" * 3000)
    rendered = sd.render_for_prompt(max_inline_chars=100)
    assert "chars" in rendered
    assert "get()" in rendered


def test_render_list_preview():
    sm = make_sm()
    sd = sm.register_store("files", "list")
    for i in range(5):
        sd._list_append(f"file{i}.py")
    rendered = sd.render_for_prompt()
    assert "5 entries" in rendered
    assert "file0.py" in rendered
    assert "..." in rendered


def test_render_dict_preview():
    sm = make_sm()
    sd = sm.register_store("tasks", "dict")
    for i in range(5):
        sd._dict_set(f"t{i}", {"name": f"Task {i}"})
    rendered = sd.render_for_prompt()
    assert "5 entries" in rendered


def test_render_empty_list():
    sm = make_sm()
    sd = sm.register_store("files", "list")
    assert sd.render_for_prompt() == "empty"


def test_render_empty_dict():
    sm = make_sm()
    sd = sm.register_store("tasks", "dict")
    assert sd.render_for_prompt() == "empty"


def test_render_for_prompt_includes_all():
    sm = make_sm()
    sm.register_store("db", "scalar")
    sm.register_store("tasks", "dict")
    sm.stores["db"]._scalar_set("staging")
    rendered = sm.render_for_prompt()
    assert "db:" in rendered
    assert "tasks:" in rendered


def test_render_operations_for_prompt():
    sm = make_sm()
    sm.register_store("tasks", "dict")
    sm.register_store("notes", "scalar")
    rendered = sm.render_operations_for_prompt()
    assert "tasks.list()" in rendered
    assert "tasks.get(id)" in rendered
    assert "tasks.set(id, value)" in rendered
    assert "notes.set(value)" in rendered


def test_render_operations_hides_writes_for_constants():
    sm = make_sm()
    sm.register_store("db", "scalar", read_only=True)
    rendered = sm.render_operations_for_prompt()
    assert "db.set" not in rendered


# ---- Persistence (file-backed) --------------------------------------


def test_file_backed_persists_automatically(tmp_path):
    sm = StateManager("run-1", state_dir=tmp_path)
    sm.register_store("notes", "scalar")
    sm.execute("notes", "set", value="hello")
    sm.close()

    # Reopen and check.
    sm2 = StateManager("run-1", state_dir=tmp_path)
    sm2.register_store("notes", "scalar")
    assert sm2.execute("notes", "get") == "hello"
    sm2.close()


def test_file_backed_dict_survives_reopen(tmp_path):
    sm = StateManager("run-2", state_dir=tmp_path)
    sm.register_store("tasks", "dict")
    sm.execute("tasks", "set", id="t1", value={"name": "Review"})
    sm.close()

    sm2 = StateManager("run-2", state_dir=tmp_path)
    sm2.register_store("tasks", "dict")
    assert sm2.execute("tasks", "get", id="t1")["name"] == "Review"
    sm2.close()


def test_state_dir_created_automatically(tmp_path):
    state_dir = tmp_path / "deep" / "nested"
    sm = StateManager("run-3", state_dir=state_dir)
    sm.register_store("x", "scalar")
    sm.execute("x", "set", value="test")
    assert (state_dir / "state" / "run-3.json").exists()
    sm.close()


def test_constants_survive_reopen(tmp_path):
    sm = StateManager("run-4", state_dir=tmp_path)
    sm.register_store("db", "scalar", read_only=True)
    sm.stores["db"]._scalar_set("staging")
    sm.close()

    sm2 = StateManager("run-4", state_dir=tmp_path)
    # Constants metadata is loaded from _meta table.
    assert "db" in sm2._constants
    sm2.register_store("db", "scalar")
    with pytest.raises(ValueError, match="read-only"):
        sm2.execute("db", "set", value="production")
    sm2.close()
