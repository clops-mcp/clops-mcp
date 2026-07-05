"""Global registry populated at class definition / module import.

Ops are keyed by a **qualified path** derived from their Python module — the
library root plus the intra-library folder hierarchy plus the Op name
(`work_ops/support/billing/HandleRefund`). This lets two libraries (or two
folders in one library) define the same bare `OpName` without colliding. A
secondary `bare-name -> [qualified path, ...]` multimap powers bare-name lookups
and disambiguation: a unique bare name resolves directly; an ambiguous one
raises rather than silently picking. See `docs/runtime-scoping-spec.md` §2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clops.op import Op
    from clops.snippet import Snippet
    from clops.tool import Tool


class AmbiguousOpName(ValueError):
    """Raised when a bare Op name resolves to more than one qualified path."""


def qualified_name(op_cls: type) -> str:
    """Return an Op's hierarchical address: `<module path>/<OpName>`.

    The path falls out of Python module structure — the library root is the
    first module segment, the rest is the intra-library folder hierarchy — so
    authors organize files and the framework derives the address (no new syntax).
    An optional class-level ``Namespace = "support/billing"`` overrides just the
    intra-library path when file layout and logical grouping diverge.
    """
    name = op_cls.__name__
    module = getattr(op_cls, "__module__", "") or ""
    override = getattr(op_cls, "Namespace", None)
    if override:
        root = module.split(".")[0] if module else ""
        parts = [root, *str(override).strip("/").split("/"), name]
    elif module:
        parts = [*module.split("."), name]
    else:
        parts = [name]
    return "/".join(p for p in parts if p)


class Registry:
    def __init__(self):
        # qualified path -> Op class
        self._ops: dict[str, type] = {}
        # bare OpName -> [qualified path, ...] (registration order)
        self._by_bare: dict[str, list[str]] = {}
        self._snippets: dict[str, "Snippet"] = {}
        self._tools: dict[str, "Tool"] = {}

    def register_op(self, op_cls: type) -> None:
        # The qualified path embeds the module, so two *different* libraries can
        # never collide here. A same-path re-registration is a module reimport
        # (the linter does this) or Python's own in-module shadowing — both
        # last-write-wins, like importlib.reload. Cross-library coexistence is
        # exactly the point: same bare name, different paths, both kept.
        qpath = qualified_name(op_cls)
        self._ops[qpath] = op_cls
        bucket = self._by_bare.setdefault(op_cls.__name__, [])
        if qpath not in bucket:
            bucket.append(qpath)

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
        """Resolve an Op by qualified path or bare name.

        A qualified path (or any exact key) returns directly. A bare name
        resolves via the multimap: unique -> that Op; none -> None; ambiguous ->
        ``AmbiguousOpName`` (callers should qualify the name).
        """
        direct = self._ops.get(name)
        if direct is not None:
            return direct
        if "/" in name:
            return None
        paths = self._by_bare.get(name)
        if not paths:
            return None
        if len(paths) == 1:
            return self._ops[paths[0]]
        raise AmbiguousOpName(
            f"Op name {name!r} is ambiguous across {sorted(paths)}; "
            "reference it by its qualified path."
        )

    def qualified_paths_for(self, bare_name: str) -> list[str]:
        """All qualified paths registered under a bare Op name (for diagnostics)."""
        return list(self._by_bare.get(bare_name, []))

    def ref(self, op_cls: type) -> str:
        """The *minimal unambiguous* reference to an Op: its bare name when that
        name is unique in the registry, else its full qualified path.

        This is what both the MCP surface (`list_processes`) and stored
        `op_name`s use — so a project keeps simple short names everywhere and
        only sees a qualified path when two Ops genuinely collide. `op(ref)`
        round-trips either form."""
        bare = op_cls.__name__
        if len(self._by_bare.get(bare, ())) <= 1:
            return bare
        return qualified_name(op_cls)

    def snippet(self, sid: str) -> "Snippet | None":
        return self._snippets.get(sid)

    def tool(self, name: str) -> "Tool | None":
        return self._tools.get(name)

    def snippets_with_role(self, role: str) -> list["Snippet"]:
        return [s for s in self._snippets.values() if s.role == role]

    def ops(self) -> dict[str, type]:
        """Map of qualified path -> Op class."""
        return dict(self._ops)

    def snippets(self) -> dict[str, "Snippet"]:
        return dict(self._snippets)

    def tools(self) -> dict[str, "Tool"]:
        return dict(self._tools)

    def clear(self) -> None:
        self._ops.clear()
        self._by_bare.clear()
        self._snippets.clear()
        self._tools.clear()


registry = Registry()
