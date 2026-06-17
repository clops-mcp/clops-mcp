"""TinyDB-backed state manager for clops runs.

Each run gets one StateManager, which owns one TinyDB instance.
Each Store declaration becomes a table within that database.

Storage layout per store type:

    Dict:   {"_key": "task-001", "name": "Review PR", "status": "pending"}
    List:   {"_value": "src/auth.py"}
    Scalar: {"_value": "staging"}
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from tinydb import TinyDB, where
from tinydb.storages import MemoryStorage


# ---- StoreData: one table, typed operations --------------------------


class StoreData:
    """Wraps one TinyDB table with typed CRUD operations."""

    def __init__(self, name: str, kind: str, table: TinyDB,
                 value_type: Any = None):
        self.name = name
        self.kind = kind
        self.table = table
        self.value_type = value_type
        self._custom_queries: dict[str, Any] = {}
        self._custom_methods: dict[str, Callable] = {}

    # ---- Scalar operations -------------------------------------------

    def _scalar_get(self) -> Any:
        docs = self.table.all()
        return docs[0]["_value"] if docs else None

    def _scalar_set(self, value: Any) -> Any:
        self.table.truncate()
        self.table.insert({"_value": value})
        return value

    # ---- List operations ---------------------------------------------

    def _list_list(self) -> list:
        return [doc["_value"] for doc in self.table.all()]

    def _list_get(self, index: int) -> Any:
        docs = self.table.all()
        idx = int(index)
        if idx < 0 or idx >= len(docs):
            raise IndexError(f"Index {idx} out of range (list has {len(docs)} entries)")
        return docs[idx]["_value"]

    def _list_append(self, value: Any) -> int:
        doc_id = self.table.insert({"_value": value})
        return doc_id

    def _list_remove(self, index: int) -> Any:
        docs = self.table.all()
        idx = int(index)
        if idx < 0 or idx >= len(docs):
            raise IndexError(f"Index {idx} out of range (list has {len(docs)} entries)")
        doc = docs[idx]
        removed = doc["_value"]
        self.table.remove(doc_ids=[doc.doc_id])
        return removed

    # ---- Dict operations ---------------------------------------------

    def _dict_list(self) -> dict:
        result = {}
        for doc in self.table.all():
            key = doc.get("_key")
            if key is not None:
                entry = {k: v for k, v in doc.items() if k != "_key"}
                # If the entry only has "_value", unwrap it.
                if list(entry.keys()) == ["_value"]:
                    result[key] = entry["_value"]
                else:
                    result[key] = entry
        return result

    def _dict_get(self, id: str) -> Any:
        doc = self.table.get(where("_key") == id)
        if doc is None:
            return None
        entry = {k: v for k, v in doc.items() if k != "_key"}
        if list(entry.keys()) == ["_value"]:
            return entry["_value"]
        return entry

    def _dict_set(self, id: str, value: Any) -> Any:
        # Remove existing entry with this key, if any.
        self.table.remove(where("_key") == id)
        if isinstance(value, dict):
            self.table.insert({"_key": id, **value})
        else:
            self.table.insert({"_key": id, "_value": value})
        return value

    def _dict_add(self, value: Any) -> str:
        key = f"id_{uuid.uuid4().hex[:8]}"
        if isinstance(value, dict):
            self.table.insert({"_key": key, **value})
        else:
            self.table.insert({"_key": key, "_value": value})
        return key

    def _dict_delete(self, id: str) -> bool:
        removed = self.table.remove(where("_key") == id)
        return len(removed) > 0

    def _dict_search(self, query) -> list[dict]:
        """Run a TinyDB query against the table."""
        results = self.table.search(query)
        return [
            {k: v for k, v in doc.items() if k != "_key"}
            for doc in results
        ]

    # ---- Dispatch ----------------------------------------------------

    _WRITE_OPS = frozenset({"set", "add", "append", "remove", "delete"})

    def execute(self, operation: str, **kwargs: Any) -> Any:
        """Route an operation to the appropriate method."""
        # Check custom queries first.
        if operation in self._custom_queries:
            return self.table.search(self._custom_queries[operation])
        if operation in self._custom_methods:
            method = self._custom_methods[operation]
            return method(self.table, **kwargs)

        if self.kind == "scalar":
            if operation == "get":
                return self._scalar_get()
            elif operation == "set":
                return self._scalar_set(kwargs["value"])
        elif self.kind == "list":
            if operation == "list":
                return self._list_list()
            elif operation == "get":
                return self._list_get(kwargs["index"])
            elif operation == "append":
                return self._list_append(kwargs["value"])
            elif operation == "remove":
                return self._list_remove(kwargs["index"])
        elif self.kind == "dict":
            if operation == "list":
                return self._dict_list()
            elif operation == "get":
                return self._dict_get(kwargs["id"])
            elif operation == "set":
                return self._dict_set(kwargs["id"], kwargs["value"])
            elif operation == "add":
                return self._dict_add(kwargs["value"])
            elif operation == "delete":
                return self._dict_delete(kwargs["id"])
            elif operation == "search":
                return self._dict_search(kwargs["query"])

        raise ValueError(
            f"Unknown operation {operation!r} for {self.kind} store {self.name!r}"
        )

    # ---- Prompt rendering --------------------------------------------

    def render_for_prompt(self, max_inline_chars: int = 2000) -> str:
        """Render this store's current value for prompt injection."""
        if self.kind == "scalar":
            val = self._scalar_get()
            if val is None:
                return "(empty)"
            serialized = json.dumps(val, default=str)
            if len(serialized) <= max_inline_chars:
                return serialized
            return f"({len(serialized)} chars — call {self.name}.get() for full value)"

        elif self.kind == "list":
            items = self._list_list()
            count = len(items)
            if count == 0:
                return "empty"
            preview = items[:3]
            preview_str = json.dumps(preview, default=str)
            suffix = ", ..." if count > 3 else ""
            return f"{count} entries, preview: {preview_str}{suffix}"

        elif self.kind == "dict":
            data = self._dict_list()
            count = len(data)
            if count == 0:
                return "empty"
            preview_keys = list(data.keys())[:3]
            preview = {k: data[k] for k in preview_keys}
            preview_str = json.dumps(preview, default=str)
            suffix = ", ..." if count > 3 else ""
            return f"{count} entries, preview: {preview_str}{suffix}"

        return "(unknown)"


# ---- StateManager: one per run ---------------------------------------


META_TABLE = "_meta"


class StateManager:
    """Manages all state stores for a single run.

    Owns a TinyDB instance (file-backed or in-memory).
    Each registered store becomes a named table.
    """

    def __init__(self, run_id: str, state_dir: Optional[Path] = None):
        self.run_id = run_id
        self.stores: dict[str, StoreData] = {}
        self._constants: set[str] = set()
        # Resolved aliases: execution_id → {alias → (store_name, bound_kwargs)}
        self._resolved_aliases: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {}

        if state_dir is not None:
            db_path = state_dir / "state" / f"{run_id}.json"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db = TinyDB(str(db_path))
        else:
            self.db = TinyDB(storage=MemoryStorage)

        # Load constants metadata if resuming.
        meta = self.db.table(META_TABLE)
        meta_docs = meta.all()
        if meta_docs:
            self._constants = set(meta_docs[0].get("constants", []))

    def register_store(self, name: str, kind: str,
                       value_type: Any = None, *,
                       read_only: bool = False,
                       custom_queries: Optional[dict[str, Any]] = None,
                       custom_methods: Optional[dict[str, Callable]] = None,
                       ) -> StoreData:
        """Register a store. Idempotent if same name+kind."""
        if name in self.stores:
            existing = self.stores[name]
            if existing.kind != kind:
                raise ValueError(
                    f"Store {name!r} already registered as {existing.kind!r}, "
                    f"cannot re-register as {kind!r}"
                )
            return existing

        table = self.db.table(name)
        sd = StoreData(name, kind, table, value_type)
        if custom_queries:
            sd._custom_queries = dict(custom_queries)
        if custom_methods:
            sd._custom_methods = dict(custom_methods)
        self.stores[name] = sd

        if read_only:
            self._constants.add(name)
            self._persist_meta()

        return sd

    def register_resolved(
        self, execution_id: str, alias: str,
        source_store: str, bound_kwargs: dict[str, Any],
    ) -> None:
        """Register a resolved alias for scoped operations.

        After Resolve runs at dispatch time, this records that e.g.
        ``current_task`` maps to ``tasks.get(id="t1")``, so the agent
        can call ``current_task.update(value=...)`` and the runtime
        translates it to ``tasks.set(id="t1", value=...)``.
        """
        if execution_id not in self._resolved_aliases:
            self._resolved_aliases[execution_id] = {}
        self._resolved_aliases[execution_id][alias] = (source_store, bound_kwargs)

    def execute(self, store_name: str, operation: str, *,
                execution_id: str | None = None, **kwargs: Any) -> Any:
        """Execute an operation on a store (or resolved alias)."""
        # Check resolved aliases first.
        if store_name not in self.stores and execution_id:
            aliases = self._resolved_aliases.get(execution_id, {})
            if store_name in aliases:
                return self._execute_alias(
                    store_name, operation, aliases[store_name], **kwargs
                )

        if store_name not in self.stores:
            raise ValueError(f"Unknown store {store_name!r}")
        if (store_name in self._constants
                and operation in StoreData._WRITE_OPS):
            raise ValueError(
                f"Store {store_name!r} is read-only (constant)"
            )
        return self.stores[store_name].execute(operation, **kwargs)

    def _execute_alias(
        self, alias: str, operation: str,
        binding: tuple[str, dict[str, Any]], **kwargs: Any,
    ) -> Any:
        """Translate a scoped alias operation to the underlying store."""
        source_store, bound_kwargs = binding
        if operation == "update":
            # current_task.update(value=X) → tasks.set(id=bound_id, value=X)
            merged = {**bound_kwargs, **kwargs}
            return self.stores[source_store].execute("set", **merged)
        elif operation == "delete":
            # current_task.delete() → tasks.delete(id=bound_id)
            return self.stores[source_store].execute("delete", **bound_kwargs)
        elif operation == "get":
            # current_task.get() → tasks.get(id=bound_id)
            return self.stores[source_store].execute("get", **bound_kwargs)
        else:
            raise ValueError(
                f"Unknown scoped operation {operation!r} on alias {alias!r}. "
                f"Available: update, delete, get."
            )

    def render_for_prompt(self,
                          visible_stores: Optional[list[str]] = None,
                          ) -> str:
        """Render all visible stores for prompt injection."""
        names = visible_stores or list(self.stores.keys())
        if not names:
            return ""
        lines = ["State:"]
        for name in names:
            store = self.stores.get(name)
            if store is None:
                continue
            rendered = store.render_for_prompt()
            kind_label = store.kind if store.kind != "scalar" else ""
            const_label = " (read-only)" if name in self._constants else ""
            if kind_label:
                lines.append(f"  {name}: {kind_label} — {rendered}{const_label}")
            else:
                lines.append(f"  {name}: {rendered}{const_label}")
            # Show value type fields if available.
            vt = store.value_type
            if vt is not None:
                fields = getattr(vt, "_fields", {})
                if fields:
                    field_parts = []
                    for f in fields.values():
                        req = "required" if f.required else "optional"
                        field_parts.append(f"{f.name} ({req})")
                    lines.append(f"    fields: {', '.join(field_parts)}")
        return "\n".join(lines)

    def render_operations_for_prompt(self,
                                     visible_stores: Optional[list[str]] = None,
                                     ) -> str:
        """Render available operations for each store."""
        names = visible_stores or list(self.stores.keys())
        if not names:
            return ""
        lines = ["State operations:"]
        for name in names:
            store = self.stores.get(name)
            if store is None:
                continue
            is_const = name in self._constants

            if store.kind == "scalar":
                if not is_const:
                    lines.append(f"  {name}.set(value)")
            elif store.kind == "list":
                lines.append(f"  {name}.list()")
                lines.append(f"  {name}.get(index)")
                if not is_const:
                    lines.append(f"  {name}.append(value)")
                    lines.append(f"  {name}.remove(index)")
            elif store.kind == "dict":
                lines.append(f"  {name}.list()")
                lines.append(f"  {name}.get(id)")
                if not is_const:
                    lines.append(f"  {name}.set(id, value)")
                    lines.append(f"  {name}.add(value)  → returns generated id")
                    lines.append(f"  {name}.delete(id)")

            # Custom queries.
            for qname in store._custom_queries:
                lines.append(f"  {name}.{qname}()")
            for mname in store._custom_methods:
                lines.append(f"  {name}.{mname}(...)")

        return "\n".join(lines)

    def close(self) -> None:
        """Close the TinyDB instance."""
        self.db.close()

    def _persist_meta(self) -> None:
        meta = self.db.table(META_TABLE)
        meta.truncate()
        meta.insert({"constants": list(self._constants)})
