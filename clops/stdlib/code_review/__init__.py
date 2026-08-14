"""Code review Op library - structured diff analysis.

This library decomposes code review into focused thought-step Ops:
- DetermineScope: identify files and change types
- SampleAndOrient: understand codebase conventions
- IdentifyBlindspots: find overlooked analysis categories
- PlanAssessment: map files to analysis lenses
- AssessFile: apply lenses to find issues
- ValidateInContext: filter false positives
- SynthesizeFindings: group and summarize
- CheckForMissedAngles: catch overlooked areas
- CompileReport: assemble structured output
- WriteSummary: executive summary

Entry point: ReviewDiff
"""

from clops.stdlib.code_review import concepts, snippets, ops

__all__ = ["concepts", "snippets", "ops"]
