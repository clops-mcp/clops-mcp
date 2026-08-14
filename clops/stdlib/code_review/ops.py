"""Code review Ops - focused thought-step decomposition."""

from clops import Op, SnippetRole, sequence

from clops.stdlib.code_review.concepts import (
    Diff,
    ScopedFiles,
    CodebaseContext,
    Blindspots,
    AssessmentPlan,
    FileFindings,
    ValidatedFindings,
    SynthesizedFindings,
    MissedAngles,
    StructuredReport,
    ExecutiveSummary,
)
from clops.stdlib.code_review.snippets import severity_guidelines, confidence_guidelines


# --- Step 1: Determine what's in scope ---
class DetermineScope(Op):
    Input = Diff
    Output = ScopedFiles
    Intent = (
        "Parse the diff to identify which files are in scope. For each file, "
        "determine:\n"
        "1. The file path\n"
        "2. Change type: new, modified, deleted, or renamed\n"
        "3. Change category: feature, refactor, bugfix, config, test, or docs\n\n"
        "Output a structured list. Focus on what changed, not why."
    )


# --- Step 2: Sample codebase to understand conventions ---
class SampleAndOrient(Op):
    Input = ScopedFiles
    Output = CodebaseContext
    Intent = (
        "From the scoped files, mentally sample 1-2 representative files to "
        "infer codebase conventions:\n"
        "- Naming conventions (camelCase, snake_case, etc.)\n"
        "- Error handling patterns (exceptions, result types, error codes)\n"
        "- Architectural style (layered, hexagonal, etc.)\n"
        "- Test conventions (naming, structure, mocking approach)\n"
        "- Logging and observability patterns\n\n"
        "Output observations that will guide assessment. Be specific about "
        "patterns you observe, not generic best practices."
    )


# --- Step 3: Identify what might be missed ---
class IdentifyBlindspots(Op):
    Input = CodebaseContext
    Output = Blindspots
    Intent = (
        "Given the scope and conventions observed, identify categories of "
        "analysis that might be overlooked:\n"
        "- File types not yet considered (configs, migrations, scripts)\n"
        "- Security angles (auth, input validation, secrets)\n"
        "- Integration points (APIs, databases, external services)\n"
        "- Performance concerns (N+1 queries, memory, concurrency)\n"
        "- Backwards compatibility (API changes, data migrations)\n\n"
        "Output a prioritized list of blindspots to check. Be specific to "
        "this codebase, not generic."
    )


# --- Step 4: Plan which lenses apply to each file ---
class PlanAssessment(Op):
    Input = Blindspots
    Output = AssessmentPlan
    Intent = (
        "For each file in scope, determine which assessment lenses apply:\n"
        "- auth: authentication/authorization logic\n"
        "- input-validation: user input handling\n"
        "- error-handling: exception/error management\n"
        "- concurrency: threading, async, race conditions\n"
        "- business-logic: correctness of domain rules\n"
        "- test-coverage: adequacy of test changes\n"
        "- api-contract: interface stability, versioning\n"
        "- performance: efficiency concerns\n\n"
        "Output a mapping of file -> applicable lenses. Not every lens "
        "applies to every file. Be selective."
    )


# --- Step 5: Assess a single file (run per-file) ---
class AssessFile(Op):
    Input = AssessmentPlan
    Output = FileFindings
    Intent = (
        "Apply the specified assessment lenses to analyze the file. For each "
        "finding, report:\n"
        "- Location: line range or function name\n"
        "- Category: which lens found this\n"
        "- Severity: critical, high, medium, or low\n"
        "- Confidence: high, medium, or low\n"
        "- Explanation: one sentence describing the issue\n\n"
        "Be thorough but precise. Report what you find, not what you expect "
        "to find. No finding is also a valid output."
    )
    Uses = [severity_guidelines, confidence_guidelines]


# --- Step 6: Validate findings in context ---
class ValidateInContext(Op):
    Input = FileFindings
    Output = ValidatedFindings
    Intent = (
        "Re-evaluate each finding in its full context:\n"
        "- Does surrounding code mitigate the risk?\n"
        "- Is the flagged pattern actually used safely here?\n"
        "- Is there framework/library behavior that makes this safe?\n"
        "- Is this an intentional tradeoff documented elsewhere?\n\n"
        "Remove false positives. For findings that stand, add a validation "
        "note explaining why. Be rigorous - uncertain findings should be "
        "downgraded in confidence, not removed."
    )
    Requires = [SnippetRole("validation")]


# --- Step 7: Synthesize findings by category ---
class SynthesizeFindings(Op):
    Input = ValidatedFindings
    Output = SynthesizedFindings
    Intent = (
        "Group validated findings by category. For each category:\n"
        "1. List the findings in that category\n"
        "2. Write a 1-2 sentence summary of what was found\n"
        "3. Note the overall severity of this category\n\n"
        "Categories with no findings can be omitted. Order categories by "
        "severity (critical first)."
    )


# --- Step 8: Check for missed angles ---
class CheckForMissedAngles(Op):
    Input = SynthesizedFindings
    Output = MissedAngles
    Intent = (
        "Review the synthesized findings against the original scope:\n"
        "- Did analysis reveal something not in the original plan?\n"
        "- Are there patterns in the findings suggesting a missed category?\n"
        "- Did any file get less attention than it deserved?\n\n"
        "Output any missed angles that warrant follow-up. If nothing was "
        "missed, say so explicitly."
    )


# --- Step 9: Compile the final report ---
class CompileReport(Op):
    Input = MissedAngles
    Output = StructuredReport
    Intent = (
        "Assemble the review into a structured markdown report:\n\n"
        "## Summary\n"
        "[Brief overview of what was reviewed]\n\n"
        "## Critical Findings\n"
        "[Any critical/high severity items - empty if none]\n\n"
        "## Findings by Category\n"
        "[Organized findings with locations and explanations]\n\n"
        "## Missed Angles\n"
        "[Any areas flagged for follow-up]\n\n"
        "## Recommendations\n"
        "[Prioritized next steps]\n\n"
        "Be concise. The report should be scannable."
    )


# --- Step 10: Write executive summary ---
class WriteSummary(Op):
    Input = StructuredReport
    Output = ExecutiveSummary
    Intent = (
        "Write a 3-5 sentence executive summary covering:\n"
        "1. What was reviewed (scope and size)\n"
        "2. The most important findings (or that none were found)\n"
        "3. Overall assessment (approve, needs changes, block)\n"
        "4. Recommended next steps\n\n"
        "This summary should let someone decide whether to read the full "
        "report. Be direct about the bottom line."
    )


# --- Main composition: the full review pipeline ---
class ReviewDiff(Op):
    Input = Diff
    Output = ExecutiveSummary
    Intent = (
        "Perform a thorough code review of the diff, decomposed into focused "
        "analysis steps: scope determination, context sampling, blindspot "
        "identification, assessment planning, file-by-file analysis, "
        "validation, synthesis, and reporting."
    )
    body = sequence(
        DetermineScope,
        SampleAndOrient,
        IdentifyBlindspots,
        PlanAssessment,
        AssessFile,
        ValidateInContext,
        SynthesizeFindings,
        CheckForMissedAngles,
        CompileReport,
        WriteSummary,
    )
    entry = True
    exit = True
