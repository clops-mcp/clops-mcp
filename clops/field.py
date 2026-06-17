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
"""

from __future__ import annotations


class Field:
    """A named, described field on a Concept.

    The metaclass sets ``name`` when it scans the Concept's namespace.
    """

    def __init__(self, description: str, *, required: bool = True):
        self.description = description
        self.required = required
        self.name: str = ""  # Set by ConceptMeta

    def __repr__(self) -> str:
        req = "required" if self.required else "optional"
        return f"Field({self.description!r}, {req}, name={self.name!r})"
