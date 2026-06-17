"""Concept: a named, described handle for things flowing between Ops.

Not a schema. The runtime value is whatever the producing agent produced.
The description is rendered into prompts as loose guidance.

Concepts may optionally declare Fields to describe their structure::

    from clops import Concept, Field

    class Task(Concept):
        description = "A work item"
        name = Field("The task name")
        status = Field("One of: pending, in_progress, done")
        assignee = Field("Who is working on this", required=False)

Fields are for agents, not for runtime validation.
"""

from __future__ import annotations

from clops.field import Field


class ConceptMeta(type):
    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        if name != "Concept" and "description" not in namespace:
            raise TypeError(f"Concept {name!r} must define a `description`.")
        cls.name = name

        # Collect Field descriptors.
        fields: dict[str, Field] = {}
        for attr_name, attr_value in namespace.items():
            if isinstance(attr_value, Field):
                attr_value.name = attr_name
                fields[attr_name] = attr_value
        cls._fields = fields

        return cls


class Concept(metaclass=ConceptMeta):
    description: str = ""
    _fields: dict[str, Field] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
