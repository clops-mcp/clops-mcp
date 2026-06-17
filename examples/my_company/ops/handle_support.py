from clops import Op, sequence
from examples.my_company.concepts import Response, UserMessage
from examples.my_company.ops.classify_intent import ClassifyIntent
from examples.my_company.ops.draft_response import DraftResponse


class HandleSupport(Op):
    Input = UserMessage
    Output = Response
    Intent = "Handle a customer support message end to end: classify, then draft."
    Meta = (
        "Top-level composition that wires ClassifyIntent into DraftResponse "
        "as a sequence. This is the entry point exposed to callers. We use "
        "a two-stage pipeline so the classification decision is visible in "
        "the execution trace and each stage can be independently iterated."
    )
    body = sequence(ClassifyIntent, DraftResponse)
    entry = True
    exit = True
