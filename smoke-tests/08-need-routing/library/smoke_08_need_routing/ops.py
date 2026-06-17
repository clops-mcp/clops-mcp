from clops import Op
from smoke_08_need_routing.concepts import Request, Triage


class TriageRequest(Op):
    Input = Request
    Output = Triage
    Intent = (
        "Triage a customer support request.\n\n"
        "REQUIRED: the input MUST contain a non-empty 'customer_id' field. "
        "If it does not, STOP. Do NOT call `complete`. Instead call:\n\n"
        "    mcp__clops__need(execution_id=<your id>, reason='missing customer_id')\n\n"
        "After the main thread resolves the need, you will be re-dispatched "
        "with a 'Supplemental input' section containing the customer_id "
        "you were missing. Use that supplemental info to complete the triage.\n\n"
        "Output format: 'Route to <team> because <reason>.'"
    )
    Meta = (
        "Demonstrates the need-routing pattern: an Op that detects missing data "
        "at runtime and raises a need for the orchestrator to resolve."
    )
    entry = True
