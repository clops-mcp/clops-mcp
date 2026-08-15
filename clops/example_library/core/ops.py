"""Standard Ops — reusable pre-work steps for any library."""

from clops import Op, SnippetRole

from clops.example_library.core.concepts import (
    DomainContext,
    ExpertSources,
    OrientedApproach,
    Topic,
)
from clops.example_library.core.snippets import landscape_intelligence, source_quality


class Research(Op):
    Input = Topic
    Output = DomainContext
    Meta = (
        "Pre-weighting step. Agents default to reasoning from training data, "
        "which is broad but shallow. This Op forces a deliberate search for "
        "authoritative sources before work begins — books and established "
        "practitioners over recent papers. The output becomes rich context "
        "that shapes all downstream reasoning."
    )
    Intent = (
        "You are given a topic or problem domain. Before any work begins, "
        "find the most authoritative sources on this subject.\n\n"
        "Process:\n"
        "1. Identify 3-5 recognized experts or practitioners in this domain. "
        "Prefer people who have written books, built real systems, or have "
        "decades of experience over people who have only published papers.\n"
        "2. For each expert, name their most important work (book, framework, "
        "or key contribution) and explain in 1-2 sentences why it matters.\n"
        "3. Identify the key mental models and frameworks these experts use "
        "to think about this domain. What are the non-obvious principles "
        "that practitioners know but outsiders miss?\n"
        "4. Note any common pitfalls or misconceptions that experts "
        "consistently warn about.\n\n"
        "Output a synthesis — not a bibliography. The goal is to give a "
        "downstream agent the mental models it needs to reason well about "
        "this domain. Structure as: key experts and why they matter, "
        "core frameworks/mental models, and common pitfalls to avoid."
    )
    Uses = [source_quality]


class Orient(Op):
    Input = Topic
    Output = OrientedApproach
    Meta = (
        "Agents default to thinking about problems like it's 2023 — write "
        "code, build a feature, deploy it. This Op reframes the problem "
        "through the lens of current agentic capabilities and the AI "
        "landscape. Uses the landscape intelligence Snippet (updated "
        "quarterly) so the framing stays current without rewriting the Op."
    )
    Intent = (
        "You are given a topic or problem to solve. Before diving into "
        "implementation, think about how to approach this in the current "
        "AI landscape (April 2026).\n\n"
        "Consider:\n"
        "1. What parts of this problem are above vs below the commodity "
        "frontier? What's already solved by off-the-shelf AI and what "
        "requires custom work?\n"
        "2. What should be an orchestration layer vs monolithic code? "
        "Where does it make sense to have agents coordinate rather than "
        "a single program executing?\n"
        "3. What's automatable now vs needs human judgment? Where is the "
        "trust boundary — what decisions can agents make autonomously vs "
        "what needs human approval?\n"
        "4. How should this be structured so that model upgrades make it "
        "better, not obsolete? What's the right level of abstraction?\n"
        "5. What capabilities don't exist yet but will in 6-12 months? "
        "Should the design account for them?\n\n"
        "Output a framing of the approach — not a plan, not code. Describe "
        "how to think about the problem, what the key structural decisions "
        "are, and what to optimize for. Be specific to this problem, not "
        "generic advice."
    )
    Requires = [SnippetRole("landscape_intelligence")]
