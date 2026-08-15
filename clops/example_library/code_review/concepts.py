"""Concepts for the code review Op library."""

from clops import Concept


class Diff(Concept):
    description = (
        "A unified diff of code changes, including file paths, hunks, "
        "added lines (+), removed lines (-), and surrounding context."
    )


class ScopedFiles(Concept):
    description = (
        "A structured list of files in scope for review, each annotated with: "
        "file path, change type (new, modified, deleted, renamed), and "
        "change category (feature, refactor, bugfix, config, test, docs)."
    )


class CodebaseContext(Concept):
    description = (
        "Observations about codebase conventions and patterns gleaned from "
        "sampling representative files: naming conventions, error handling "
        "patterns, architectural style, test conventions, logging approach."
    )


class Blindspots(Concept):
    description = (
        "A list of analysis categories that might be overlooked given the "
        "current scope: file types not considered, security angles, "
        "integration points, performance concerns, backwards compatibility."
    )


class AssessmentPlan(Concept):
    description = (
        "A per-file assessment plan mapping each file to the analysis lenses "
        "that apply: auth, input-validation, error-handling, concurrency, "
        "business-logic, test-coverage, API-contract, etc."
    )


class FileFindings(Concept):
    description = (
        "Findings from analyzing the files in scope. Each finding includes: "
        "file path, location (line range), category, severity "
        "(critical/high/medium/low), confidence (high/medium/low), and a "
        "one-sentence explanation."
    )


class ValidatedFindings(Concept):
    description = (
        "Findings that have been re-evaluated in full context. False positives "
        "removed, remaining findings annotated with validation notes explaining "
        "why the finding stands."
    )


class SynthesizedFindings(Concept):
    description = (
        "Findings grouped by category with a short summary per category "
        "explaining what was found and its significance to the change."
    )


class MissedAngles(Concept):
    description = (
        "Analysis angles that emerged during review but weren't in the "
        "original plan, flagged for follow-up investigation."
    )


class StructuredReport(Concept):
    description = (
        "A markdown-formatted code review report with sections for: "
        "summary, critical findings, categorized findings, missed angles, "
        "and recommended actions."
    )


class ExecutiveSummary(Concept):
    description = (
        "A 3-5 sentence summary covering: what was reviewed, the most "
        "important findings, overall assessment, and recommended next steps."
    )
