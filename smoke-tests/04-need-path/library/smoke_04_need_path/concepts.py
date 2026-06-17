from clops import Concept


class SupportRequest(Concept):
    description = (
        "A customer support request. Required fields: 'customer_id' (string) "
        "and 'message' (string). If 'customer_id' is missing or empty, the "
        "request cannot be processed."
    )


class Triage(Concept):
    description = "A short triage decision: which team should handle this request, and why."
