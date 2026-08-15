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
from clops.stdlib.code_review.tools import grep_pattern, read_file


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
    Meta = (
        "'Review this code' is too broad — the agent freelances. This is the "
        "first constraint on that: fix an inventory of what changed before any "
        "judgment gets attached to it. The change category (feature, refactor, "
        "config, test) is what later lets PlanAssessment pick lenses per file "
        "instead of applying every lens everywhere. Deliberately mechanical — "
        "a good candidate for a faster model."
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
    Meta = (
        "Without a read on local convention, findings collapse into generic "
        "best practice — naming nits and 'add error handling here' that ignore "
        "how this codebase already works. Sampling one or two representative "
        "files first gives every later step something specific to measure the "
        "diff against. Two files, not twenty: the point is to calibrate, not "
        "to re-read the repository."
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
    Meta = (
        "Agents overlook whole categories confidently — they assess business "
        "logic and never think about auth. This asks 'what would I miss?' "
        "before the assessment plan exists, so the answer can change the plan "
        "rather than arrive as a caveat at the end. It runs on the conventions "
        "just observed, so the blindspots named are specific to this codebase. "
        "CheckForMissedAngles does the same job later, against findings."
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
    Meta = (
        "Choosing a lens and applying it are different judgments; done at "
        "once, each file gets whatever analysis came to mind first. This "
        "commits to a file-to-lens mapping up front, informed by the "
        "blindspots just named, so AssessFile answers a bounded question per "
        "file. The instruction to be selective carries as much weight as the "
        "lens list — every lens on every file is the same as no plan."
    )


# --- Step 5: Assess the files the plan names (one pass, no fan-out) ---
class AssessFile(Op):
    Input = AssessmentPlan
    Output = FileFindings
    Intent = (
        "Apply the assessment lenses the plan assigns to each file it names.\n\n"
        "The plan reaches you without the code attached. Read the code before "
        "judging it: `read_file` returns a file from the project under review "
        "with line numbers, and `grep_pattern` finds a usage or a pattern "
        "across the tree. Assess a file only after you have read it. If the "
        "plan names no path you can read, call `need` rather than assessing "
        "the plan itself.\n\n"
        "For each finding, report:\n"
        "- File: the path assessed\n"
        "- Location: line range or function name\n"
        "- Category: which lens found this\n"
        "- Severity: critical, high, medium, or low\n"
        "- Confidence: high, medium, or low\n"
        "- Explanation: one sentence describing the issue\n\n"
        "Be thorough but precise. Report what you find, not what you expect "
        "to find. No finding is also a valid output."
    )
    Meta = (
        "The analysis step proper, kept narrow: apply the lenses the plan "
        "assigned and report what is actually there. A sequence carries only "
        "the previous step's output, so the plan arrives here with no code "
        "attached — `read_file` and `grep_pattern` are how the Op reaches the "
        "files the plan names, which is cheaper and less lossy than having "
        "every upstream step re-emit the diff to carry it forward. Severity "
        "and confidence come from pinned Snippets rather than the Intent so "
        "the scale stays consistent across files and can be retuned in one "
        "place. 'No finding is also a valid output' is load-bearing — a step "
        "that must produce something will, and validation downstream then "
        "spends itself on noise."
    )
    Uses = [severity_guidelines, confidence_guidelines]
    Tools = [read_file, grep_pattern]


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
    Meta = (
        "Findings generated in isolation have a high false positive rate. "
        "This step exists because agents confidently flag patterns that are "
        "actually safe once the surrounding code is visible. Combining it with "
        "AssessFile was considered and rejected — the context switch hurt "
        "accuracy. The false-positive list is declared as a Snippet role "
        "rather than pinned, so a project can register its own in place of "
        "the stdlib one."
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
    Meta = (
        "A flat list of validated findings is a queue, not a review. Grouping "
        "by category and summarizing each group is what turns 'nine issues' "
        "into 'error handling is missing at every boundary, plus three "
        "unrelated nits' — the difference between a report that gets acted on "
        "and one that gets skimmed. Kept separate from CompileReport because "
        "this step is the judgment and that one is layout."
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
    Meta = (
        "Self-correction after the fact. The assessment plan was written "
        "before anything had been analyzed, so the findings are themselves "
        "evidence about whether the plan was right — three unrelated "
        "error-handling bugs argue for looking at error handling everywhere, "
        "not only where the plan said to. Requiring an explicit 'nothing was "
        "missed' rather than allowing silence keeps the step from quietly "
        "becoming a no-op."
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
    Meta = (
        "Assembly, not analysis — every judgment in the report was made "
        "upstream and this step only lays it out. The section order is fixed "
        "so a reader can find the critical findings without reading the whole "
        "thing. Because the work is mechanical, this is the clearest candidate "
        "in the library for a faster model, or eventually for a Tool that "
        "concatenates the upstream sections with no LLM call at all."
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
    Meta = (
        "The summary decides whether the rest of the report gets read, so it "
        "has to land on a verdict — approve, needs changes, block — not a "
        "description of what was looked at. It summarizes the compiled report "
        "rather than the raw findings, so the bottom line it states is one the "
        "reader can verify in the sections directly below. Three to five "
        "sentences is a ceiling, not a target."
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
    Meta = (
        "Ten focused steps instead of one 'review this code' dispatch — the "
        "failure this library exists to avoid, since an undecomposed review "
        "freelances and whatever it never considered leaves no trace in the "
        "output. Orientation precedes planning, validation precedes synthesis, "
        "and self-correction sits at both ends of the plan: IdentifyBlindspots "
        "before it, CheckForMissedAngles after the findings. The per-file "
        "fan-out and the programmatic verification step from the original "
        "sketch are not wired here — AssessFile runs once, in sequence."
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
