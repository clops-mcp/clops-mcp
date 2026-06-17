from clops import Op
from smoke_04_need_path.concepts import SupportRequest, Triage


class TriageRequest(Op):
    Input = SupportRequest
    Output = Triage
    Intent = (
        "Triage a customer support request. The input MUST contain a non-empty "
        "'customer_id' field. If 'customer_id' is missing or empty, you CANNOT "
        "proceed — call `mcp__clops__need` with the exact reason "
        "'missing customer_id'. Do not attempt to triage without it.\n\n"
        "If 'customer_id' is present, return a one-sentence triage decision "
        "of the form 'Route to <team> because <reason>.'"
    )
    Meta = (
        "Validates the need path — an Op that detects missing prerequisites and signals "
        "back to the orchestrator instead of hallucinating a result."
    )
    entry = True
