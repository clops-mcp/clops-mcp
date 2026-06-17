"""Tests for the Store descriptor (Phase 1)."""

from __future__ import annotations

from typing import Any

import pytest

from clops import Concept, Op, Store


class Task(Concept):
    description = "A work item"


class Brief(Concept):
    description = "A project brief"


class Result(Concept):
    description = "A result"


# ---- Type resolution -------------------------------------------------


def test_store_scalar_str():
    s = Store(str)
    assert s.kind == "scalar"
    assert s.value_type is str


def test_store_scalar_int():
    s = Store(int)
    assert s.kind == "scalar"
    assert s.value_type is int


def test_store_list_type():
    s = Store(list[Task])
    assert s.kind == "list"
    assert s.value_type is Task


def test_store_dict_type():
    s = Store(dict[str, Task])
    assert s.kind == "dict"
    assert s.value_type is Task


def test_store_default_is_scalar_str():
    s = Store()
    assert s.kind == "scalar"
    assert s.value_type is str


def test_store_description():
    s = Store(str, description="Active database")
    assert s.description == "Active database"


# ---- OpMeta collection -----------------------------------------------


def test_op_collects_stores():
    class MyOp(Op):
        Input = Brief
        Output = Result
        Intent = "Do work"
        Meta = "Test Op with stores."

        tasks = Store(dict[str, Task])
        notes = Store(str)

    assert len(MyOp._stores) == 2
    assert "tasks" in MyOp._stores
    assert "notes" in MyOp._stores


def test_op_without_stores_has_empty_dict():
    class PlainOp(Op):
        Input = Brief
        Output = Result
        Intent = "No stores"
        Meta = "Test Op without stores."

    assert hasattr(PlainOp, "_stores")
    assert len(PlainOp._stores) == 0


def test_store_name_set_by_metaclass():
    class NamedOp(Op):
        Input = Brief
        Output = Result
        Intent = "Check names"
        Meta = "Test Op for store naming."

        my_tasks = Store(dict[str, Task])
        my_notes = Store(str)

    assert NamedOp._stores["my_tasks"].name == "my_tasks"
    assert NamedOp._stores["my_notes"].name == "my_notes"


def test_store_on_leaf_op():
    """Leaf Ops (no body) can declare stores."""
    class LeafWithStore(Op):
        Input = Brief
        Output = Result
        Intent = "Leaf with state"
        Meta = "Test leaf Op with store."
        entry = True

        progress = Store(str)

    assert "progress" in LeafWithStore._stores


def test_store_on_composition_op():
    """Composition Ops can declare stores."""
    class StepA(Op):
        Input = Brief
        Output = Result
        Intent = "Step A"
        Meta = "Step A."

    class StepB(Op):
        Input = Result
        Output = Result
        Intent = "Step B"
        Meta = "Step B."

    from clops import sequence

    class Pipeline(Op):
        Input = Brief
        Output = Result
        Intent = "Pipeline with state"
        Meta = "Test composition Op with store."
        entry = True
        body = sequence(StepA, StepB)

        tasks = Store(dict[str, Task])

    assert "tasks" in Pipeline._stores
    assert Pipeline._stores["tasks"].kind == "dict"
