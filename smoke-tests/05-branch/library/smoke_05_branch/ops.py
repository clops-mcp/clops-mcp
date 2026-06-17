from clops import Op, branch_on, sequence
from smoke_05_branch.concepts import Category, Message, Reply


class Triage(Op):
    Input = Message
    Output = Category
    Intent = (
        "Classify the user's message into one of three categories: "
        "billing, technical, or general. Reply with EXACTLY one lowercase "
        "word — billing, technical, or general — and nothing else. "
        "Do not explain, do not punctuate, do not capitalize."
    )
    Meta = (
        "Classification step that produces the branch key — demonstrates an Op whose "
        "output drives downstream routing via branch_on."
    )


class HandleBilling(Op):
    Input = Category
    Output = Reply
    Intent = "Reply with a one-sentence acknowledgment for a billing issue."
    Meta = "Leaf handler for the 'billing' branch arm — one of three arms that prove branch_on dispatches correctly."


class HandleTechnical(Op):
    Input = Category
    Output = Reply
    Intent = "Reply with a one-sentence acknowledgment for a technical issue."
    Meta = "Leaf handler for the 'technical' branch arm — structurally identical to HandleBilling to isolate routing from handler logic."


class HandleGeneral(Op):
    Input = Category
    Output = Reply
    Intent = "Reply with a one-sentence acknowledgment for a general inquiry."
    Meta = "Leaf handler for the 'general' branch arm — the fallback category, ensuring all classification outputs have a handler."


def _category_of(triage_output) -> str:
    """Pull the category out of the triage subagent's output (prose)."""
    text = str(triage_output).strip().lower()
    for category in ("billing", "technical", "general"):
        if category in text:
            return category
    return text  # falls through; missing-arm error will surface


class Route(Op):
    Input = Message
    Output = Reply
    Intent = "Triage the message, then route to the matching handler."
    Meta = (
        "Composite Op combining sequence and branch_on — validates that classification "
        "output can drive dynamic dispatch to one of several handler Ops."
    )
    body = sequence(
        Triage,
        branch_on(
            key=_category_of,
            arms={
                "billing": HandleBilling,
                "technical": HandleTechnical,
                "general": HandleGeneral,
            },
        ),
    )
    entry = True
