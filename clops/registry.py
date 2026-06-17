"""Global registry populated at class definition / module import."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clops.op import Op
    from clops.snippet import Snippet
    from clops.tool import Tool


class Registry:
    def __init__(self):
        self._ops: dict[str, type] = {}
        self._snippets: dict[str, "Snippet"] = {}
        self._tools: dict[str, "Tool"] = {}

    def register_op(self, op_cls: type) -> None:
        existing = self._ops.get(op_cls.__name__)
        if (existing is not None and existing is not op_cls
                and getattr(existing, "__module__", None) != getattr(op_cls, "__module__", None)):
            raise ValueError(
                f"Op name {op_cls.__name__!r} is already registered by module "
                f"{existing.__module__!r}; {op_cls.__module__!r} cannot reuse it. "
                "Op names must be unique across loaded libraries."
            )
        self._ops[op_cls.__name__] = op_cls

    def register_snippet(self, snippet: "Snippet") -> None:
        existing = self._snippets.get(snippet.id)
        if existing is not None and existing != snippet:
            raise ValueError(
                f"Snippet {snippet.id!r} already registered with different content."
            )
        self._snippets[snippet.id] = snippet

    def register_tool(self, tool: "Tool") -> None:
        existing = self._tools.get(tool.name)
        if existing is not None and existing is not tool:
            existing_key = (existing.name, existing.description)
            new_key = (tool.name, tool.description)
            if existing_key != new_key:
                raise ValueError(
                    f"Tool {tool.name!r} already registered with different metadata."
                )
        self._tools[tool.name] = tool

    def op(self, name: str) -> type | None:
        return self._ops.get(name)

    def snippet(self, sid: str) -> "Snippet | None":
        return self._snippets.get(sid)

    def tool(self, name: str) -> "Tool | None":
        return self._tools.get(name)

    def snippets_with_role(self, role: str) -> list["Snippet"]:
        return [s for s in self._snippets.values() if s.role == role]

    def ops(self) -> dict[str, type]:
        return dict(self._ops)

    def snippets(self) -> dict[str, "Snippet"]:
        return dict(self._snippets)

    def tools(self) -> dict[str, "Tool"]:
        return dict(self._tools)

    def clear(self) -> None:
        self._ops.clear()
        self._snippets.clear()
        self._tools.clear()


registry = Registry()
