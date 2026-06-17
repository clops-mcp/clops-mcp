"""Resolve — pre-computed state queries parameterized by input variables.

Ops declare a ``Resolve`` field mapping names to query specs:

    Resolve = {
        "current_task": {
            "store": "tasks",
            "op": "get",
            "bind": {"id": "input.task_id"},
        },
    }

At dispatch time the runtime evaluates these against the StateManager
and the raw input, injecting the results into the prompt as
"Resolved context" with scoped write operations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ResolvedItem:
    """One resolved query result, with metadata for scoped operations."""
    name: str
    value: Any
    source_store: str
    source_op: str
    bound_kwargs: dict[str, Any] = field(default_factory=dict)


def _extract_value(source: str, input_data: Any) -> Any:
    """Resolve a dotted source reference like ``input.task_id``."""
    parts = source.split(".", 1)
    if len(parts) != 2:
        return None
    namespace, key = parts
    if namespace == "input":
        if isinstance(input_data, dict):
            return input_data.get(key)
        # Try JSON-parsing string input.
        if isinstance(input_data, str):
            try:
                parsed = json.loads(input_data)
                if isinstance(parsed, dict):
                    return parsed.get(key)
            except (json.JSONDecodeError, TypeError):
                pass
    return None


def resolve(
    spec: dict[str, dict],
    state_manager: Any,
    input_data: Any,
) -> list[ResolvedItem]:
    """Evaluate Resolve specs against state and input.

    Returns a list of ResolvedItem with values and scoped-operation metadata.
    """
    results: list[ResolvedItem] = []
    for name, query in spec.items():
        store_name = query.get("store", "")
        operation = query.get("op", "get")
        bind = query.get("bind", {})

        kwargs: dict[str, Any] = {}
        for param, source in bind.items():
            kwargs[param] = _extract_value(source, input_data)

        try:
            value = state_manager.execute(store_name, operation, **kwargs)
        except (ValueError, KeyError, IndexError):
            value = None

        results.append(ResolvedItem(
            name=name,
            value=value,
            source_store=store_name,
            source_op=operation,
            bound_kwargs=kwargs,
        ))
    return results


def render_resolved_for_prompt(items: list[ResolvedItem]) -> str:
    """Render resolved context for the agent's prompt."""
    if not items:
        return ""
    lines = ["## Resolved context"]
    for item in items:
        val_str = json.dumps(item.value, default=str, indent=None)
        if len(val_str) > 500:
            val_str = val_str[:500] + "..."
        lines.append(f"  {item.name}: {val_str}")
        # Scoped operations for dict get results.
        if item.source_op == "get" and "id" in item.bound_kwargs and item.value is not None:
            lines.append(
                f"    → {item.name}.update(value)  "
                f"[updates {item.source_store}[{item.bound_kwargs['id']!r}]]"
            )
            lines.append(
                f"    → {item.name}.delete()  "
                f"[removes {item.source_store}[{item.bound_kwargs['id']!r}]]"
            )
    return "\n".join(lines)
