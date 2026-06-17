"""Store descriptor for declaring typed state stores on Ops.

Usage::

    class ProjectOverseer(Op):
        Input = ProjectBrief
        Output = CompletedProject
        Intent = "Oversee the project to completion"

        tasks = Store(dict[str, Task])
        notes = Store(str)
        current_db = Store(str, description="Active database connection")

Store types determine available operations:

- Scalar (str, int, bool): get, set
- List (list[X]): list, get, append, remove
- Dict (dict[str, X]): list, get, set, add, delete, search

Custom queries via subclassing::

    from tinydb import where

    class TaskStore(Store):
        type_hint = dict[str, Task]
        queries = {
            "pending": where('status') == 'pending',
            "done": where('status') == 'done',
        }

        def by_assignee(self, table, assignee: str):
            return table.search(where('assignee') == assignee)
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, get_args, get_origin


class Store:
    """Descriptor declaring a named, typed state store on an Op.

    The metaclass sets ``name`` when it scans the Op's namespace.
    The runtime uses ``kind`` and ``value_type`` to create the
    appropriate TinyDB-backed store at run start.

    Subclasses can define:
    - ``queries``: dict of name → TinyDB query expression (static)
    - Custom methods: ``def my_query(self, table, **kwargs)`` (parameterized)
    """

    # Class-level attributes for subclassing.
    queries: dict[str, Any] = {}

    def __init__(self, type_hint: Any = None, *, description: str = ""):
        # Subclasses can set type_hint as a class attribute; fall back to str.
        if type_hint is not None:
            self.type_hint = type_hint
        elif not hasattr(self, "type_hint") or self.type_hint is None:
            self.type_hint = str
        # else: keep the class-level type_hint from the subclass.
        self.description = description
        self.name: str = ""  # Set by OpMeta
        self.kind: str = self._resolve_kind(self.type_hint)
        self.value_type: Any = self._resolve_value_type(self.type_hint)
        # Collect custom queries from the class (for subclasses).
        self._static_queries: dict[str, Any] = dict(self.__class__.queries)
        self._custom_methods: dict[str, Callable] = {}
        # Only collect methods defined directly on the subclass (not Store).
        for attr_name, attr in self.__class__.__dict__.items():
            if attr_name.startswith("_"):
                continue
            if attr_name in ("queries", "type_hint"):
                continue
            if inspect.isfunction(attr):
                self._custom_methods[attr_name] = attr

    @staticmethod
    def _resolve_kind(type_hint: Any) -> str:
        origin = get_origin(type_hint)
        if origin is dict:
            return "dict"
        elif origin is list:
            return "list"
        else:
            return "scalar"

    @staticmethod
    def _resolve_value_type(type_hint: Any) -> Any:
        origin = get_origin(type_hint)
        if origin is dict:
            args = get_args(type_hint)
            return args[1] if len(args) > 1 else Any
        elif origin is list:
            args = get_args(type_hint)
            return args[0] if args else Any
        else:
            return type_hint

    def custom_query_names(self) -> list[str]:
        """All custom query names (static + method-based)."""
        return sorted(set(self._static_queries) | set(self._custom_methods))

    def __repr__(self) -> str:
        return f"Store({self.type_hint!r}, name={self.name!r}, kind={self.kind!r})"
