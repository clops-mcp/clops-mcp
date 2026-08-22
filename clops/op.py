"""Op: the single unifying computation primitive.

Leaf Ops have no `body` and become an LLM dispatch.
Composition Ops have a `body` built from combinators.
The framework never distinguishes leaves from compositions at the call site.
"""

from __future__ import annotations

import types
import typing
from typing import Any, ClassVar


def _unpack_output(value) -> tuple | None:
    """Normalize an Op.Output declaration into a tuple of types.

    Accepts:
      - A single class -> (value,)
      - typing.Union[A, B, ...] -> (A, B, ...)
      - A | B syntax (types.UnionType) -> (A, B)
      - A tuple (A, B, ...) -> (A, B, ...)

    Returns None if the value doesn't match any of these shapes.
    """
    if isinstance(value, type):
        return (value,)
    if isinstance(value, tuple):
        return value
    origin = typing.get_origin(value)
    if origin is typing.Union or origin is types.UnionType:
        return typing.get_args(value)
    return None


class OpMeta(type):
    """Metaclass: validates shape and registers at class definition time."""

    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        if name == "Op" or namespace.get("_abstract", False):
            return cls

        from clops.concept import Concept
        from clops.registry import registry

        errors: list[str] = []

        intent = namespace.get("Intent")
        if not isinstance(intent, str) or not intent.strip():
            errors.append(f"Op {name!r} must define a non-empty `Intent` string.")

        meta = namespace.get("Meta")
        if not isinstance(meta, str) or not meta.strip():
            errors.append(
                f"Op {name!r} must define a non-empty `Meta` string "
                "(why this Op exists, what approach it takes, and what was considered)."
            )

        # Teammates (persistent sub-agents) were removed from the runtime.
        # Reject their attributes loudly instead of silently ignoring them.
        for removed in ("Team", "persistence", "Init"):
            if removed in namespace:
                errors.append(
                    f"Op {name!r} declares `{removed}`, which belonged to the removed "
                    "teammate feature (persistent sub-agents). The runtime no longer "
                    "honors it — delete the attribute."
                )

        input_cls = namespace.get("Input")
        output_cls = namespace.get("Output")
        if input_cls is None:
            errors.append(f"Op {name!r} must define `Input` as a Concept subclass.")
        elif not (isinstance(input_cls, type) and issubclass(input_cls, Concept)):
            errors.append(f"Op {name!r}.Input must be a Concept subclass.")

        output_variants: tuple = ()
        if output_cls is None:
            errors.append(f"Op {name!r} must define `Output` as a Concept subclass.")
        else:
            # Normalize Output into a tuple of Concept subclasses.
            # Workers must declare a single Output Concept.
            members = _unpack_output(output_cls)
            if members is None:
                errors.append(
                    f"Op {name!r}.Output must be a Concept subclass."
                )
            elif not members:
                errors.append(f"Op {name!r}.Output must be non-empty.")
            elif not all(
                isinstance(m, type) and issubclass(m, Concept) for m in members
            ):
                offenders = [m for m in members if not (isinstance(m, type) and issubclass(m, Concept))]
                errors.append(
                    f"Op {name!r}.Output has non-Concept member(s): {offenders!r}."
                )
            elif len(members) > 1:
                errors.append(
                    f"Op {name!r}.Output must be a single Output Concept."
                )
            else:
                output_variants = tuple(members)
                # Stash the normalized tuple on the class so the renderer
                # can iterate without re-unpacking.
                namespace["_output_variants"] = output_variants

        # Validate Tools entries: must be Tool instances or Op subclasses.
        tools = namespace.get("Tools")
        if tools:
            from clops.tool import Tool

            for i, entry in enumerate(tools):
                if isinstance(entry, Tool):
                    continue
                if isinstance(entry, type) and issubclass(entry, Op):
                    # Op subroutine reference — valid
                    continue
                errors.append(
                    f"Op {name!r}.Tools[{i}] must be a Tool instance or an Op class; "
                    f"got {entry!r}."
                )

        # Collect Store descriptors.
        from clops.store import Store as _StoreCls

        stores: dict[str, _StoreCls] = {}
        for attr_name, attr_value in namespace.items():
            if isinstance(attr_value, _StoreCls):
                attr_value.name = attr_name
                stores[attr_name] = attr_value
        cls._stores = stores

        if errors:
            raise TypeError("\n".join(errors))

        # Attach the normalized output variants so renderers + downstream
        # code can iterate. Always set, even on Op-base itself (empty tuple).
        cls._output_variants = output_variants

        registry.register_op(cls)
        return cls


class Op(metaclass=OpMeta):
    """Base class for every Op.

    Required on every concrete Op (the metaclass raises TypeError otherwise):
        Input: Concept subclass
        Output: exactly one Concept subclass
        Intent: non-empty string — purpose + anti-scope. Rendered into
            the dispatched prompt.
        Meta: non-empty string — why this Op exists, what approach it
            takes, what was considered. NOT rendered into the prompt; it
            documents the library for whoever inherits it.

    Optional, and honored by the runtime:
        Uses: list of pinned Snippets / Op references
        Requires: list of SnippetRole soft declarations
        Tools: list of Tool instances and/or Op subclasses (subroutines)
        Model: model override for this Op's dispatch
        body: combinator tree for composition Ops
        entry: marks a top-level entry point — the procedure tag, read by
            list_processes() and start()

    Declared but NOT consumed anywhere in the runtime. They accept values
    and do nothing; treat them as reserved, not as features:
        Examples: never rendered into the prompt
        exit: nothing reads it — only `entry` affects dispatch
        before_run / after_run: no callback hook exists
    """

    Input: ClassVar[type]
    Output: ClassVar[type]
    Intent: ClassVar[str] = ""
    Meta: ClassVar[str] = ""

    Uses: ClassVar[list] = []
    Requires: ClassVar[list] = []
    Tools: ClassVar[list] = []
    Examples: ClassVar[list] = []

    Model: ClassVar[str | None] = None
    body: ClassVar[Any] = None
    entry: ClassVar[bool] = False
    exit: ClassVar[bool] = False

    _abstract: ClassVar[bool] = True

    @classmethod
    def is_leaf(cls) -> bool:
        return cls.body is None
