"""Tool: external capability exposed to an Op during reasoning.

A Tool is a name, a description, an argument hint and a Python handler.
Declaring one registers it. An Op lists Tools it may use; the renderer
describes them in the dispatched prompt, and the agent invokes one
through the single ``call_tool`` MCP entry, which looks the Tool up in
the registry and runs its handler.

``parameters`` is a ``{name: type}`` hint rendered into the prompt. It is
not validated at runtime. ``handler`` is optional: a Tool without one can
be referenced and described, but calling it fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    handler: Optional[Callable[..., Any]] = None

    def __post_init__(self):
        if not self.name:
            raise ValueError("Tool.name must be non-empty.")
        if not self.description:
            raise ValueError(f"Tool {self.name!r}.description must be non-empty.")
        from clops.registry import registry

        registry.register_tool(self)
