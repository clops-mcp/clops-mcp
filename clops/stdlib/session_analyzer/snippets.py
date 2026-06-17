"""Snippets -- reusable content fragments injected into Op prompts."""

from clops import Snippet

evaluation_criteria = Snippet(
    id="session_analyzer_evaluation_criteria",
    content=(
        "When evaluating Op outputs against Intents, apply these criteria:\n"
        "1. COMPLETENESS: Does the output address every element the Intent requested?\n"
        "2. CONSTRAINT ADHERENCE: Does the output respect every constraint "
        "(format, length, scope) the Intent specified?\n"
        "3. SCOPE DISCIPLINE: Does the output avoid adding content the Intent "
        "did not request?\n"
        "4. OUTPUT SHAPE: Does the output match the structural format the Intent "
        "described (e.g., list vs. prose, specific fields)?\n"
        "5. REASONING DEPTH: Is the reasoning proportional to the task -- "
        "neither superficial nor over-elaborated?"
    ),
    role="evaluation_criteria",
)

token_efficiency_rules = Snippet(
    id="session_analyzer_token_efficiency",
    content=(
        "Token efficiency heuristics for identifying waste:\n"
        "- A step that produces fewer than 50 output tokens but consumed over "
        "2000 input tokens may indicate an over-specified prompt or unnecessary context.\n"
        "- A step whose output is a deterministic transformation of its input "
        "(concatenation, filtering, formatting) should be a programmatic Tool, "
        "not an LLM call.\n"
        "- A step that repeats large portions of its input verbatim in its output "
        "is wasting tokens on copying.\n"
        "- Multiple steps with near-identical Intents differing only in a parameter "
        "suggest a missing parameterized Tool or a gather pattern.\n"
        "- Steps using expensive models for simple classification or extraction "
        "tasks could use cheaper models."
    ),
    role="efficiency_rules",
)

op_design_principles = Snippet(
    id="session_analyzer_op_design",
    content=(
        "Op design principles to evaluate against:\n"
        "- Single responsibility: one Op = one focused cognitive step.\n"
        "- If an Op's Intent is longer than a short paragraph, it is likely "
        "doing too much and should be split.\n"
        "- Deterministic work (parsing, concatenation, filtering, formatting) "
        "should use Tools, not LLM calls.\n"
        "- Analytical domains need tight Intents specifying exact criteria, "
        "output structure, and what counts as a finding.\n"
        "- Self-correction patterns (blindspot detection, contextual validation, "
        "verification) should be present in analytical workflows.\n"
        "- Compositions should use gather for independent parallel work and "
        "sequence for dependent steps.\n"
        "- Snippets should capture recurring policy, rules, or guardrails "
        "rather than embedding them in every Intent."
    ),
    role="design_principles",
)

pattern_catalog = Snippet(
    id="session_analyzer_pattern_catalog",
    content=(
        "Pattern types to scan for in Op library sessions:\n"
        "- 'token_waste': LLM doing deterministic work (concat, reformat, filter) "
        "or copying input verbatim into output.\n"
        "- 'missing_decomposition': One step doing multiple unrelated cognitive "
        "actions (Intent has 'then'/'also' joining independent instructions).\n"
        "- 'unnecessary_llm_call': Output fully predictable from input without "
        "judgment; same structure regardless of content.\n"
        "- 'missing_tool': LLM doing lookup/calculation/retrieval a function could handle.\n"
        "- 'weak_intent': Vague Intent using 'handle'/'process'/'deal with' without "
        "specifying criteria or output shape.\n"
        "- 'missing_self_correction': Findings go to output without re-evaluation; "
        "no blindspot/validation/verification steps.\n"
        "- 'model_mismatch': Simple task on expensive model, or complex task on cheap model.\n"
        "- 'redundant_steps': Steps with substantially overlapping Intents or outputs.\n"
        "- 'missing_snippet': Identical policy/rules text repeated across multiple Intents."
    ),
    role="pattern_catalog",
)

blindspot_categories = Snippet(
    id="session_analyzer_blindspot_categories",
    content=(
        "Blindspot categories to check after primary analysis:\n"
        "- 'composition_structure': Wrong flow shape -- sequential steps that could "
        "be parallel, missing branch arms, missing loop termination.\n"
        "- 'error_handling': Steps that silently swallow errors or produce empty "
        "results on unexpected input; no graceful degradation.\n"
        "- 'concept_design': Concepts too broad (carry unneeded data) or too narrow "
        "(force hallucination of missing info).\n"
        "- 'missing_validation': Analysis outputs go to final result without being "
        "re-evaluated in context; no false-positive filtering.\n"
        "- 'teammate_misuse': Single-turn teammates (should be Ops), overly broad "
        "queries, insufficient Init context.\n"
        "- 'loop_termination': Fragile or missing termination conditions in loops.\n"
        "- 'branch_coverage': Realistic input categories not covered; fragile key function.\n"
        "- 'snippet_opportunity': Rules/policies hardcoded in Intents that should be Snippets."
    ),
    role="blindspot_categories",
)
