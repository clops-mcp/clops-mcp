from clops import Concept


class UserMessage(Concept):
    description = (
        "A customer's support message, including any context that came with it "
        "(customer ID, channel, recent activity)."
    )


class Intent(Concept):
    description = (
        "A classification of the customer's support need. "
        "Categories: billing, technical, or general. "
        "Includes reasoning for the classification and a rough sense of confidence."
    )


class Response(Concept):
    description = (
        "A proposed response to the customer, in prose. "
        "Should acknowledge the issue, state resolution or next steps, "
        "and match brand voice."
    )
