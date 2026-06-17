from clops import Concept


class Topic(Concept):
    description = "A short topic to research from multiple angles."


class Term(Concept):
    description = "A single technical term to define."


class Definition(Concept):
    description = "A one-sentence, plain-language definition of a term."


class Angle(Concept):
    description = (
        "One paragraph of perspective on the topic from a specific angle. "
        "Self-contained; can stand on its own."
    )


class Brief(Concept):
    description = (
        "A short synthesis paragraph that combines multiple angle perspectives "
        "into a single coherent brief."
    )
