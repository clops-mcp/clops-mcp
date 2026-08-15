"""Standard Snippets — reusable guardrails and context."""

from clops import Snippet


# ---------------------------------------------------------------------------
# Research quality criteria
# ---------------------------------------------------------------------------

source_quality = Snippet(
    id="stdlib_source_quality",
    content=(
        "Source quality hierarchy for research:\n"
        "1. Books by recognized practitioners (highest signal — survived "
        "editorial process, represents years of accumulated thinking)\n"
        "2. Established frameworks from named experts with track records\n"
        "3. Conference talks and long-form essays by practitioners\n"
        "4. Peer-reviewed papers in top venues (but beware: paper volume "
        "has exploded and quality varies wildly — prioritize citations "
        "and author reputation over recency)\n"
        "5. Blog posts from recognized experts (useful for current thinking, "
        "but lower bar for rigor)\n\n"
        "Avoid: AI-generated summaries of other sources, papers with no "
        "citations, content farms, and anything that reads like it was "
        "written to game search rankings.\n\n"
        "When in doubt, prefer fewer high-quality sources over many "
        "mediocre ones. Three great books beat twenty random papers."
    ),
    role="research_quality",
)


# ---------------------------------------------------------------------------
# Landscape intelligence (updated quarterly)
# ---------------------------------------------------------------------------

landscape_intelligence = Snippet(
    id="stdlib_landscape_intelligence",
    content=(
        "AI Landscape Intelligence — April 2026\n\n"

        "KEY STRUCTURAL FACTS:\n"
        "- Model layer is commoditizing: API prices collapsed 80%+ in 12 months. "
        "Capabilities go from differentiated to commodity in 12-18 months.\n"
        "- 60% of new code in 2026 is AI-generated. 90% of developers use AI coding tools.\n"
        "- 40% of ~14,000 AI startups launched in 2024 shut down by early 2026. "
        "60-70% of AI wrappers generate zero revenue.\n\n"

        "COMMODITY FRONTIER (what's already commodity vs still differentiable):\n"
        "- Commodity NOW: text generation, RAG, basic coding assistance\n"
        "- Commodity in 6-12mo: complex multi-step reasoning, voice-to-structured output\n"
        "- Commodity in 12-18mo: agentic tool use\n"
        "- Still differentiable (2-3yr): proprietary workflow integration\n"
        "- Durable (3-5yr): longitudinal user data (if compounding), "
        "high-stakes decision support with accountability\n\n"

        "WHAT WORKS:\n"
        "- Products that consume AI as input and add proprietary workflow/domain structure\n"
        "- Workflow embedding creates switching costs that compound\n"
        "- Each model upgrade should make your product better, not obsolete\n"
        "- Agent pattern: agent proposes, user approves, agent executes\n\n"

        "WHAT FAILS:\n"
        "- Thin AI wrappers with no workflow embedding\n"
        "- Building moats from technical AI differentiation (erodes in 3-12mo)\n"
        "- Prompt engineering / UX wrapper advantages (3-6mo)\n"
        "- First-mover advantage alone (6-12mo)\n\n"

        "AGENTIC THINKING:\n"
        "- Products become orchestration layers — value shifts from making "
        "the model useful to giving it the right context, tools, and guardrails\n"
        "- Multi-step autonomous agents become production-reliable ~Apr 2027\n"
        "- By Apr 2028: ambient products that understand context and act proactively\n"
        "- Design for model upgrades: structure so frontier improvements increase your value\n\n"

        "IMPLICATION FOR OP DESIGN:\n"
        "- Think about whether each step needs an LLM or could be programmatic\n"
        "- Consider what's above vs below the commodity frontier\n"
        "- Build orchestration, not monolithic solutions\n"
        "- Embed in workflows — don't just generate output\n"
        "- Plan for capabilities that don't exist yet becoming available in 6-12 months"
    ),
    role="landscape_intelligence",
)
