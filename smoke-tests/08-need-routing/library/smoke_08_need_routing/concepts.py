from clops import Concept


class Request(Concept):
    description = (
        "A customer support request. Must include a 'customer_id' field. "
        "If it is missing or empty, the Op cannot proceed and MUST call "
        "`mcp__clops__need(execution_id=…, reason='missing customer_id')` "
        "so the main thread can resolve."
    )


class Triage(Concept):
    description = "A short triage decision: which team to route to, and why."
