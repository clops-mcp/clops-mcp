"""Concepts for smoke test 14: the file hand-off contract.

Deliberately worded so that nothing here mentions files. The workspace and the
rule that long results go in one are rendered by the runtime; if a Concept
described the hand-off, the scenario would be testing its own fixture.
"""

from clops import Concept, Field


class Topic(Concept):
    description = "A subject to write about at length."

    subject = Field("What the document should cover")


class Specification(Concept):
    description = "A long, detailed written specification."

    content = Field("The specification itself, in full detail")


class Assessment(Concept):
    description = "A short critical assessment of a specification."

    verdict = Field("Whether the specification is complete enough to build from")
    gaps = Field("Anything material the specification leaves out", required=False)
