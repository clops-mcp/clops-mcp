"""business_designer -- clops Op library for designing agent-based systems.

Three-diamond flow for architecting business processes as agent systems:
- Diamond 1 (WHAT): BroadScan -> PrioritizeScope
- Diamond 2 (HOW): ExploreDesigns -> SelectDesign
- Diamond 3 (WHO): DecomposeAgents -> DefineAgents
- Validation: FailureAnalysis + GapCheck (parallel) -> CompileSpecs

Entry point: DesignBusinessAgents
"""

from clops.example_library.business_designer import concepts, snippets, ops  # noqa: F401

__all__ = ["concepts", "snippets", "ops"]
