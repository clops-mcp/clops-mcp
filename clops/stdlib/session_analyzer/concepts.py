"""Concepts -- named, described handles for data flowing between Ops."""

from clops import Concept


class SessionTranscript(Concept):
    description = (
        "A raw session transcript from a clops execution. Contains "
        "the full text log of an Op library run, including Op dispatch records, "
        "LLM inputs/outputs, tool calls, teammate exchanges, and timing data. "
        "May be plain text or structured (JSON lines, markdown sections)."
    )


class ParsedSession(Concept):
    description = (
        "Structured representation of a session transcript, extracted by a "
        "deterministic parser. Contains a list of step records, each with: "
        "op_name (str), intent (str -- the Op's declared Intent), "
        "input_summary (str), output_text (str), tools_called (list[str]), "
        "teammate_exchanges (list[dict]), token_counts (dict with "
        "'input_tokens' and 'output_tokens'), duration_ms (int or null), "
        "and model (str or null). Also includes session-level metadata: "
        "total_steps, total_tokens, entry_op, and library_name."
    )


class StepEvaluation(Concept):
    description = (
        "Per-step evaluation results. A list of evaluated steps, each with: "
        "op_name (str), verdict ('aligned' | 'drifted' | 'underspecified'), "
        "issues (list of {issue_type: str from ['omitted_element', "
        "'unrequested_content', 'ignored_constraint', 'format_violation', "
        "'ambiguous_intent'], evidence: str, severity: 'high' | 'medium' | 'low'}), "
        "token_efficiency (str -- 'appropriate' | 'over_reasoned' | "
        "'under_reasoned'), and notes (str -- brief free-text observation)."
    )


class PatternAnalysis(Concept):
    description = (
        "Cross-step pattern analysis identifying systemic issues in the Op "
        "library design. Contains a list of patterns, each with: "
        "pattern_type (str from ['token_waste', 'missing_decomposition', "
        "'unnecessary_llm_call', 'missing_tool', 'weak_intent', "
        "'missing_self_correction', 'model_mismatch', 'redundant_steps', "
        "'missing_snippet']), affected_ops (list[str]), evidence (str -- "
        "specific transcript excerpts or metrics supporting the finding), "
        "confidence ('high' | 'medium' | 'low'), and suggestion (str -- "
        "one-sentence actionable fix)."
    )


class BlindspotFindings(Concept):
    description = (
        "Results of a blindspot check that re-examines the session from "
        "angles the step-level and pattern-level analyses may have missed. "
        "Contains a list of findings, each with: category (str from "
        "['composition_structure', 'error_handling', 'concept_design', "
        "'missing_validation', 'teammate_misuse', 'loop_termination', "
        "'branch_coverage', 'snippet_opportunity']), description (str), "
        "evidence (str), and priority ('high' | 'medium' | 'low'). "
        "If no blindspots found, the list is empty with a note explaining "
        "what was checked."
    )


class ImprovementPlan(Concept):
    description = (
        "A prioritized improvement plan for the Op library, synthesized from "
        "all prior analyses. Contains: executive_summary (str -- 2-3 sentences), "
        "improvements (list ordered by priority, each with: title (str), "
        "category (str from ['intent_rewrite', 'op_split', 'op_merge', "
        "'tool_replacement', 'model_change', 'snippet_addition', "
        "'concept_refinement', 'composition_restructure', 'self_correction_add']), "
        "affected_ops (list[str]), current_behavior (str), proposed_behavior (str), "
        "expected_impact (str from ['high', 'medium', 'low']), "
        "effort (str from ['trivial', 'small', 'medium', 'large'])), "
        "and metrics_to_watch (list[str] -- what to measure after changes)."
    )
