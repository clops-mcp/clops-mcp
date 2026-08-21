"""Op: the single unifying computation primitive.

Leaf Ops have no `body` and become an LLM dispatch.
Composition Ops have a `body` built from combinators.
The framework never distinguishes leaves from compositions at the call site.
"""

from __future__ import annotations

import re
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


#: Cap on a process's one-line description in `list_processes(descriptions=True)`.
#: Long enough to say what a process does, short enough that a catalog of fifty
#: still fits in a glance.
SHORT_DESCRIPTION_MAX = 160

# A sentence terminator followed by whitespace (or the end of the line). The
# lookbehind keeps the punctuation in the sentence we return.
_SENTENCE_END = re.compile(r"(?<=[.!?])(\s|$)")

# A colon or semicolon usually introduces the detail the summary is trying to
# drop ("...using a three-diamond structure: first discover what processes
# exist, then...") so it makes a better cut than the sentence end.
_CLAUSE_BREAK = re.compile(r"[:;]")

# ...but only once enough of a clause precedes it. Cutting at the colon in a
# label-style Intent ("Goal: review the diff") would leave the word "Goal".
_MIN_CLAUSE = 40

#: Roughly what a whole described catalog should cost to read, in characters.
#: Not a hard ceiling — see `description_cap_for`, which spends it.
DESCRIPTION_BUDGET = 2000

#: Below this a description stops being one, so the budget gives way rather
#: than shaving every line down to a stub.
MIN_DESCRIPTION = 60


def description_cap_for(count: int) -> int:
    """How long each description may be when listing `count` processes.

    `SHORT_DESCRIPTION_MAX` bounds one line; nothing bounded the listing. Three
    processes cost 500 characters, which is the feature working — but a library
    with eighty of them costs 13,000, and an agent that asked "what can I run?"
    has just paid more for the answer than for most of the work. So the budget
    is spent across the catalog: small catalogs get the full line, large ones
    get terser ones, and past `MIN_DESCRIPTION` the shrinking stops — a
    forty-character stub is not a cheaper description, it is a worse one.

    The escape hatch is the filter: `list_processes(processes=[...])` narrows
    the count, so asking about five processes buys full-length lines for those
    five however big the library is.
    """
    if count <= 0:
        return SHORT_DESCRIPTION_MAX
    return max(MIN_DESCRIPTION, min(SHORT_DESCRIPTION_MAX, DESCRIPTION_BUDGET // count))


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rstrip()
    space = cut.rfind(" ")
    if space > max_chars // 2:  # Don't strip most of the line chasing a word break.
        cut = cut[:space].rstrip()
    return cut + "\u2026"


def short_description(op_cls: type, *, max_chars: int = SHORT_DESCRIPTION_MAX) -> str:
    """A one-line gist of an Op, for catalog listings.

    `Intent` is written for the subagent that will execute the Op, so it is
    long by design — steps, output shape, anti-scope. Rendering fifty of those
    to answer "what can this project run?" buries the answer. This returns the
    first clause of the first line instead — up to the first sentence end, or
    to the colon that introduces the detail, whichever comes first — which for
    a well-written Intent is exactly the gist.

    An Op that wants control over its one-liner declares `Summary`; it wins
    over the derived text. Both are capped at `max_chars` — a `Summary` that
    isn't short doesn't get to un-shorten the listing.
    """
    explicit = getattr(op_cls, "Summary", None)
    if isinstance(explicit, str) and explicit.strip():
        return _truncate(" ".join(explicit.split()), max_chars)

    intent = getattr(op_cls, "Intent", "")
    if not isinstance(intent, str) or not intent.strip():
        return ""
    line = intent.strip().split("\n", 1)[0].strip()

    cut = len(line)
    sentence = _SENTENCE_END.search(line)
    if sentence:
        cut = sentence.start()
    clause = _CLAUSE_BREAK.search(line, _MIN_CLAUSE)
    if clause and clause.start() < cut:
        cut = clause.start()

    return _truncate(line[:cut].strip(), max_chars)


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
                    "honors it — delete the attribute. "
                    "See docs/migration-interpreter-swap.md."
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

    Required on every concrete Op:
        Input: Concept subclass
        Output: Concept subclass
        Intent: non-empty docstring describing purpose + anti-scope
        Meta: why this Op exists, what approach it takes, what was considered

    Optional:
        Summary: one-line gist for `list_processes` (derived from Intent if absent)
        Uses: list of pinned Snippets / Op references
        Requires: list of SnippetRole soft declarations
        Tools: list of Tool instances
        Examples: iterable of few-shot demonstrations
        Model: optional model override
        before_run / after_run: callbacks
        body: combinator tree for composition Ops
        entry / exit: bool markers for entry/exit Ops
    """

    Input: ClassVar[type]
    Output: ClassVar[type]
    Intent: ClassVar[str] = ""
    Meta: ClassVar[str] = ""

    # Optional one-liner for the process catalog. Absent, `short_description`
    # derives one from Intent — so this is an override, never a requirement.
    Summary: ClassVar[str] = ""

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
