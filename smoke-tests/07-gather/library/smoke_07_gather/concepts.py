from clops import Concept


class Topic(Concept):
    description = "A short topic to research from multiple angles."


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
