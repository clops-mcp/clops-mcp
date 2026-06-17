from clops import Concept


class Message(Concept):
    description = "An incoming user message."


class Category(Concept):
    description = (
        "A category label as a single lowercase word — exactly one of: "
        "billing, technical, general. Nothing else."
    )


class Reply(Concept):
    description = "A short reply suitable for the routed handler."
