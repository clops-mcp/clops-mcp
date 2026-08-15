"""Ops -- process reflection and thinking extraction from sessions."""

from clops import Op, SnippetRole, sequence
from clops.example_library.session_analyzer.concepts import (
    ImprovementPlan,
    ParsedSession,
    SessionTranscript,
)
from clops.example_library.session_analyzer.snippets import evaluation_criteria, op_design_principles
from clops.example_library.session_analyzer.tools import load_session, parse_transcript, summarize_session


# ---------------------------------------------------------------------------
# Step 1: Parse (programmatic — same as before)
# ---------------------------------------------------------------------------

class ParseTranscript(Op):
    Input = SessionTranscript
    Output = ParsedSession
    Meta = "Transcript parsing is deterministic — no LLM reasoning needed. Uses load_session to find logs by session ID and parse_transcript for structured extraction."
    Intent = (
        "You are given a session ID. Use the `summarize_session` tool to "
        "produce a compact conversation digest. This strips tool results "
        "and system noise, keeping only the human-agent dialogue.\n\n"
        "Present the digest as-is. Do not analyze or evaluate — just "
        "pass the conversation through for downstream Ops to work with."
    )
    Tools = [load_session, parse_transcript, summarize_session]


# ---------------------------------------------------------------------------
# Step 2: Find the moments that mattered
# ---------------------------------------------------------------------------

class FindInflectionPoints(Op):
    Input = ParsedSession
    Output = ParsedSession  # reuses concept — enriched with inflection annotations
    Meta = (
        "Most turns in a session are execution. A few are moments where the "
        "direction, understanding, or approach fundamentally shifted. These "
        "inflection points are where the real learning happened. Finding "
        "10-15 out of hundreds of turns focuses analysis on what matters."
    )
    Intent = (
        "Scan the parsed session for moments where the process itself changed — "
        "not every decision, but the moments that altered the trajectory.\n\n"
        "Types of inflection points:\n"
        "- Reframes: the way of thinking about the problem changed\n"
        "- Course corrections: the human steered the agent in a different direction\n"
        "- Discoveries: something was tried and revealed unexpected information\n"
        "- Breakthroughs: a principle or pattern crystallized\n"
        "- Pivots: an approach was abandoned for a fundamentally different one\n\n"
        "For each inflection point (10-15 maximum):\n"
        "- What moment was it? (quote or paraphrase the key exchange)\n"
        "- What type? (reframe, correction, discovery, breakthrough, pivot)\n"
        "- What was the trajectory before vs after?\n"
        "- What context had been building up that made this moment happen?\n\n"
        "Skip routine execution. If the agent built something and it worked "
        "as expected, that's not an inflection point. If it built something "
        "and the failure revealed a new principle — that is."
    )


# ---------------------------------------------------------------------------
# Step 3: Extract what we were thinking about
# ---------------------------------------------------------------------------

class ExtractThinkingContext(Op):
    Input = ParsedSession
    Output = ParsedSession  # enriched with thinking patterns
    Meta = (
        "The most valuable thing in a session isn't what was done — it's "
        "what considerations were active while doing it. This Op extracts "
        "the thinking patterns: what trade-offs were being weighed, what "
        "principles were being applied, what the human was optimizing for. "
        "This is the raw material for priming future agents."
    )
    Intent = (
        "Using the inflection points as anchors, extract the thinking that "
        "was active during this session.\n\n"
        "For each inflection point and the work surrounding it:\n"
        "- What considerations were in play? (not what was decided — what "
        "was being weighed)\n"
        "- What trade-offs were being navigated? (speed vs quality, "
        "specificity vs flexibility, build now vs defer)\n"
        "- What principles were being applied, explicitly or implicitly?\n"
        "- What was the human optimizing for that the agent might not "
        "have figured out on its own?\n\n"
        "Then zoom out:\n"
        "- What thinking patterns repeated across multiple inflection points?\n"
        "- What considerations were always active vs situation-specific?\n"
        "- What would an agent need to be thinking about to arrive at the "
        "same inflection points without human steering?\n\n"
        "Output the thinking patterns, not a narrative of what happened."
    )


# ---------------------------------------------------------------------------
# Step 4: Identify what thinking led to the best outcomes
# ---------------------------------------------------------------------------

class EvaluateThinkingEffectiveness(Op):
    Input = ParsedSession
    Output = ParsedSession  # enriched with effectiveness judgments
    Meta = (
        "Not all thinking is equally valuable. Some considerations led to "
        "breakthroughs, others were discussed and abandoned. This step "
        "separates the thinking that actually produced good outcomes from "
        "the thinking that was noise."
    )
    Intent = (
        "Review the thinking patterns extracted in the previous step. "
        "For each one, evaluate:\n\n"
        "- Did this thinking lead to a concrete outcome? (a design decision, "
        "a principle that got encoded, a tool that got built)\n"
        "- Would the outcome have been worse without this thinking? "
        "(counterfactual test: if the agent had skipped this consideration, "
        "what would have happened?)\n"
        "- Is this thinking specific to this session/project or is it "
        "generalizable?\n\n"
        "Classify each thinking pattern as:\n"
        "- Essential: directly caused good outcomes, generalizable\n"
        "- Situational: helped here, but tied to this specific context\n"
        "- Noise: discussed but didn't meaningfully affect outcomes\n\n"
        "Focus on the 'essential' patterns — these are what we want to "
        "encode as priming for future agents."
    )


# ---------------------------------------------------------------------------
# Step 5: Translate thinking into guidance
# ---------------------------------------------------------------------------

class EncodeAsPriming(Op):
    Input = ParsedSession
    Output = ImprovementPlan  # reused — but now contains priming artifacts
    Meta = (
        "The final translation: from observed thinking patterns to encoded "
        "guidance. Not instructions ('do X') but context that induces the "
        "right reasoning ('here's what matters and why'). The output is "
        "draft Snippets, Intent refinements, and flow structure suggestions "
        "that carry the thinking forward."
    )
    Intent = (
        "Take the essential thinking patterns from the previous step and "
        "translate them into clops artifacts:\n\n"
        "1. SNIPPETS: For each essential thinking pattern, draft a Snippet "
        "that would prime an agent to think about the same considerations. "
        "Don't write instructions — write context. Explain what matters, "
        "why it matters, and what happens when you ignore it. The agent "
        "should read the Snippet and internalize the reasoning, not just "
        "follow a rule.\n\n"
        "2. INTENT REFINEMENTS: If any existing Op Intents would benefit "
        "from incorporating these thinking patterns, suggest specific "
        "additions. Show the current Intent and the proposed change.\n\n"
        "3. FLOW PATTERNS: If the session revealed a process shape that "
        "should be encoded as a standard flow (e.g., 'always research "
        "before building', 'validate against real data before declaring "
        "done'), describe the flow structure.\n\n"
        "4. SESSION MEMORY: Produce a concise update for the project's "
        "CLAUDE.md — not duplicating docs, but capturing: open threads, "
        "active principles not yet in docs, and how we work on this project.\n\n"
        "For each artifact, note whether it's project-specific or should "
        "go into stdlib."
    )
    Uses = [evaluation_criteria, op_design_principles]


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

class AnalyzeSession(Op):
    Input = SessionTranscript
    Output = ImprovementPlan
    Meta = (
        "Process reflection flow. Not about finding bugs — about understanding "
        "how we think during effective sessions and encoding that thinking "
        "as minimal, effective guidance for future agents. The output is "
        "priming artifacts (Snippets, Intent refinements, flow patterns) "
        "that induce the right reasoning without heavy-handed instructions."
    )
    Intent = (
        "Analyze a session transcript to extract the thinking patterns that "
        "made it effective, then encode those patterns as guidance artifacts "
        "for future agents."
    )
    body = sequence(
        ParseTranscript,
        FindInflectionPoints,
        ExtractThinkingContext,
        EvaluateThinkingEffectiveness,
        EncodeAsPriming,
    )
    entry = True
