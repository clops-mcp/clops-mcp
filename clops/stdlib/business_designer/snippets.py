"""Snippets -- guardrail fragments injected into Op prompts."""

from clops import Snippet


high_achiever_bar = Snippet(
    id="business_designer_high_achiever_bar",
    role="quality_bar",
    content=(
        "For every design decision, articulate the difference between "
        "'adequate' and 'great'. Adequate solves the stated problem. Great "
        "anticipates the next three problems, reduces future coordination "
        "costs, and makes the system easier to change when assumptions turn "
        "out wrong.\n\n"
        "Concretely: when you pick an approach, state what 'adequate' would "
        "look like and then what 'great' looks like. If your chosen design "
        "is only adequate, say so and explain why the cost of great isn't "
        "worth it here. If you can't articulate the difference, you haven't "
        "thought hard enough."
    ),
)


failure_mode_forcing = Snippet(
    id="business_designer_failure_mode_forcing",
    role="failure_analysis",
    content=(
        "Every component you design must answer: 'How does this break?'\n\n"
        "Not 'could this break?' -- everything breaks. The questions are:\n"
        "- What's the most likely failure mode?\n"
        "- What's the most expensive failure mode?\n"
        "- How long before someone notices?\n"
        "- What's the recovery path -- and does the recovery itself have "
        "failure modes?\n\n"
        "If you describe a component without describing how it fails, the "
        "description is incomplete. A design without failure analysis is a "
        "wish, not a plan."
    ),
)


reality_check = Snippet(
    id="business_designer_reality_check",
    role="reality_check",
    content=(
        "Flag the gap between theory and likely actual behavior.\n\n"
        "For each process or agent you design, ask: 'In practice, will this "
        "actually work as described?' Common gaps:\n"
        "- The design assumes data that doesn't exist or is unreliable\n"
        "- The design assumes a handoff that will be dropped in practice\n"
        "- The design assumes model capabilities beyond what's reliable today\n"
        "- The design assumes humans will follow the prescribed process\n"
        "- The design works for the happy path but breaks on edge cases that "
        "are actually common\n\n"
        "When you spot a theory-vs-reality gap, name it explicitly. Don't "
        "just note the risk -- describe what will actually happen."
    ),
)


simplicity_bias = Snippet(
    id="business_designer_simplicity_bias",
    role="simplicity",
    content=(
        "Fewer moving parts means fewer failure modes. Default to simple.\n\n"
        "Rules:\n"
        "- One agent doing two things is simpler than two agents coordinating. "
        "Only split when the trust boundary, cognitive load, or failure "
        "isolation genuinely requires it.\n"
        "- A sequence of three Ops is simpler than a gather of three Ops. "
        "Only parallelize when the time savings justify the coordination cost.\n"
        "- A hardcoded rule is simpler than an LLM call. Only use LLM "
        "reasoning when the task genuinely requires judgment.\n"
        "- Every additional agent, Op, or connection is a liability until "
        "proven otherwise.\n\n"
        "When you add complexity, name what you're buying with it. 'This is "
        "more complex because X, which is worth it because Y.' If you can't "
        "finish that sentence, simplify."
    ),
)


decision_journal = Snippet(
    id="business_designer_decision_journal",
    role="decision_journal",
    content=(
        "Document not just what was chosen but what was rejected and why.\n\n"
        "For every significant decision (process selection, design approach, "
        "agent boundary, composition structure):\n"
        "- State the decision clearly\n"
        "- List what was considered (minimum 2 alternatives)\n"
        "- For each rejected option, give the specific reason it lost -- not "
        "'it was worse' but 'it required X which we don't have' or 'it "
        "introduces Y failure mode that Z doesn't'\n"
        "- Name what would make you revisit this decision\n\n"
        "This isn't bureaucracy -- it's future-proofing. When assumptions "
        "change, the person reading this (possibly you, 3 months from now) "
        "needs to know which decisions to reopen."
    ),
)
