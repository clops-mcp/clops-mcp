"""Field descriptor for typed Concept fields.

Usage::

    from clops import Concept, Field

    class Task(Concept):
        description = "A work item"

        name = Field("The task name")
        status = Field("One of: pending, in_progress, done")
        assignee = Field("Who is working on this", required=False)

Fields are for agents, not for runtime validation. They tell agents
what to provide (inputs) and what to expect (outputs). The runtime
renders them in prompts alongside the Concept description.

There is no type parameter, and the renderer does not recurse into
nested Concepts, so a composite field has to describe its own shape in
prose. That pushes authors toward long field descriptions, and a long
description of an unbounded collection is an instruction to emit that
collection inline -- onto the relay, where bulk does not belong.

``bulk=True`` marks a field as carrying an unbounded collection::

    class FlowManifest(Concept):
        description = "A manifest of the characterised flows."

        handle = Field("the handle holding the full flow records")
        flow_count = Field("how many records are behind the handle")
        flows = Field("the full flow records", bulk=True)

The marker is a declaration, not an enforcement: the renderer tells the
agent to relay a reference and a count for that field rather than its
contents, and the linter warns when an Output declares nothing but bulk.
"""

from __future__ import annotations


class Field:
    """A named, described field on a Concept.

    The metaclass sets ``name`` when it scans the Concept's namespace.

    Args:
        description: What the field holds, in prose. Must be
            self-sufficient -- nothing else describes the field's shape.
        required: Whether the producing agent must supply it.
        bulk: Whether the field carries an unbounded collection. Bulk
            fields are rendered with an instruction to relay a reference
            and a count instead of the contents.
    """

    def __init__(
        self,
        description: str,
        *,
        required: bool = True,
        bulk: bool = False,
    ):
        self.description = description
        self.required = required
        self.bulk = bulk
        self.name: str = ""  # Set by ConceptMeta

    def __repr__(self) -> str:
        req = "required" if self.required else "optional"
        mark = ", bulk" if self.bulk else ""
        return f"Field({self.description!r}, {req}{mark}, name={self.name!r})"
