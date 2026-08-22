"""Ops for smoke test 14: long results hand off through the run workspace.

DraftAndAssess (entry, composition):
  body = sequence(DraftSpec, AssessSpec)

DraftSpec (leaf):
  Asked for a long document. Nothing tells it to write a file — the runtime's
  workspace section is the only thing that does, which is the point.

AssessSpec (leaf):
  Receives whatever DraftSpec handed back. If the contract held, that is a
  summary and a path, and this step has to open the file to do its job.
"""

from clops import Op, sequence
from smoke_14_workspace.concepts import Assessment, Specification, Topic


class DraftSpec(Op):
    Input = Topic
    Output = Specification
    Intent = (
        "Write a thorough technical specification for the subject you were "
        "given. Cover scope, the data model, the interfaces, failure modes, "
        "and open questions. Be exhaustive — this should read like a document "
        "a team could build from, not a summary of one. Aim for well over a "
        "thousand words."
    )
    Meta = (
        "Produces a deliberately long result. Exists to exercise the file "
        "hand-off contract, so its Intent must not mention files: the runtime's "
        "workspace section has to be what carries that."
    )


class AssessSpec(Op):
    Input = Specification
    Output = Assessment
    Intent = (
        "Assess the specification you were given. Say whether it is complete "
        "enough for a team to build from, and name anything material it leaves "
        "out. Be specific: cite the parts you are judging."
    )
    Meta = (
        "Consumes the previous step's long result. Cannot be answered from a "
        "summary alone, so it shows whether the path it received actually "
        "resolves to the work."
    )


class DraftAndAssess(Op):
    Input = Topic
    Output = Assessment
    Intent = "Draft a detailed specification, then assess it."
    Meta = "Two leaves, the first of which produces far more than fits inline."
    entry = True

    body = sequence(DraftSpec, AssessSpec)
