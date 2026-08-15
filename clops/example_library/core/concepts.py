"""Standard Concepts shared across libraries."""

from clops import Concept


class Topic(Concept):
    description = "A subject, domain, or problem area to investigate."


class ExpertSources(Concept):
    description = (
        "Curated authoritative sources on a topic: books, key authors, "
        "foundational papers, and why each source matters. Prioritizes "
        "books and established practitioners over recent papers."
    )


class DomainContext(Concept):
    description = (
        "Synthesized expert knowledge on a topic: key frameworks, mental "
        "models, common pitfalls, and how practitioners think about the "
        "domain. Designed to pre-weight an agent's reasoning before it "
        "starts working."
    )


class OrientedApproach(Concept):
    description = (
        "A problem framed through the lens of current agentic capabilities: "
        "what's automatable, what needs judgment, what's above vs below "
        "the commodity frontier, and how to structure the solution as an "
        "orchestration layer rather than monolithic code."
    )
