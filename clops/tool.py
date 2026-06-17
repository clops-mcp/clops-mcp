"""Tool: external capability exposed to an Op during reasoning.

Phase 0 placeholder — holds metadata only. Dispatch/invocation comes in Phase 1.
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
