"""Ops -- the units of computation for business/process design."""

from clops import Op, SnippetRole, gather, sequence

from clops.stdlib.business_designer.concepts import (
    AgentDefinitions,
    AgentOptions,
    BusinessContext,
    DesignGaps,
    DesignOptions,
    FailureModes,
    OpLibrarySpecs,
    ProcessLandscape,
    ScopedProcesses,
    SelectedDesigns,
)
from clops.stdlib.business_designer.snippets import (
    decision_journal,
    failure_mode_forcing,
    high_achiever_bar,
    reality_check,
    simplicity_bias,
)


# ---------------------------------------------------------------------------
# Diamond 1: WHAT processes exist?
# ---------------------------------------------------------------------------

class BroadScan(Op):
    """Divergent -- surface every process, especially the unnamed ones."""

    Input = BusinessContext
    Output = ProcessLandscape
    Intent = (
        "You are given a description of a business or system. Map the full "
        "landscape of processes before narrowing anything.\n\n"
        "For each process identified, answer four questions:\n"
        "1. TRIGGER: What starts it? (user action, schedule, another process, "
        "external event)\n"
        "2. STAKEHOLDER: Who cares about the output? (customer, internal "
        "team, another system, regulator)\n"
        "3. FAILURE IMPACT: What happens if it doesn't run? (nothing, "
        "revenue loss, safety issue, customer churn, compliance violation)\n"
        "4. DECOMPOSITION: Is this actually one process or multiple processes "
        "wearing one name? If multiple, list each sub-process separately.\n\n"
        "Push past the first 5-6 obvious processes. Specifically look for:\n"
        "- Processes that exist in the gaps between named ones (handoff "
        "coordination, exception handling, escalation routing)\n"
        "- Manual work nobody thinks of as a 'process' (triaging emails, "
        "copying data between systems, verifying outputs)\n"
        "- Processes triggered by failure of other processes (retry logic, "
        "customer complaint handling, data reconciliation)\n\n"
        "Output the full landscape as a list of process entries. Over-include "
        "rather than under-include -- the next step handles prioritization."
    )
    Meta = (
        "Agents converge too fast -- they want to jump to the 4-5 obvious "
        "processes and start designing. This step forces broad exploration "
        "before any decisions by requiring structured answers about each "
        "process and explicitly pushing for the non-obvious ones. Without "
        "this, the entire downstream design is built on an incomplete map."
    )
    Uses = [reality_check]


class PrioritizeScope(Op):
    """Convergent -- select what to design now vs defer."""

    Input = ProcessLandscape
    Output = ScopedProcesses
    Intent = (
        "Given the full process landscape, select which processes to design "
        "now and which to defer.\n\n"
        "Evaluate each process on three criteria:\n"
        "1. IMPACT: How much does this process matter? Be specific -- "
        "'high impact' means nothing. State the impact type: revenue at risk "
        "(how much?), time saved (how many hours/week?), error reduction "
        "(what error rate?), compliance requirement (what regulation?), "
        "or customer experience (what metric?).\n"
        "2. FEASIBILITY: Can agents reliably handle this today? What model "
        "capabilities does it require? What data does it need access to? "
        "If it needs capabilities that don't exist yet, defer it.\n"
        "3. DEPENDENCIES: Which processes must exist before others can work? "
        "A downstream process that depends on an upstream one not yet built "
        "should be deferred unless both are selected.\n\n"
        "Output three sections:\n"
        "- SELECTED: Ordered by priority. Each entry: process name, impact "
        "type and magnitude, feasibility assessment, and rationale.\n"
        "- DEFERRED: Each entry: process name and the specific condition "
        "that would move it up (not 'when we have more time' -- 'when X "
        "capability exists' or 'after Y process is running').\n"
        "- DEPENDENCIES: Which selected processes must be built in what order."
    )
    Meta = (
        "Not everything should be designed at once, but agents resist "
        "deferring work -- they want to be comprehensive. This step forces "
        "explicit prioritization with concrete criteria. The deferred list "
        "with specific promotion conditions prevents work from being silently "
        "dropped and gives a clear re-entry path."
    )
    Uses = [decision_journal, simplicity_bias]


# ---------------------------------------------------------------------------
# Diamond 2: HOW should each process work?
# ---------------------------------------------------------------------------

class ExploreDesigns(Op):
    """Divergent -- generate structurally different approaches per process."""

    Input = ScopedProcesses
    Output = DesignOptions
    Intent = (
        "For each scoped process, generate 2-3 fundamentally different "
        "design approaches. Not variations on one theme -- structurally "
        "different designs that make different trade-offs.\n\n"
        "For each approach, provide:\n"
        "- CORE IDEA: One sentence describing the structural approach.\n"
        "- AUTOMATION LEVEL: What's fully automated, what's human-in-the-loop, "
        "and where the approval gates are.\n"
        "- LLM vs PROGRAMMATIC: Which steps need LLM reasoning (judgment, "
        "synthesis, classification) vs deterministic tools (lookups, "
        "calculations, formatting, API calls).\n"
        "- MAIN RISK: The single biggest way this approach could fail.\n"
        "- CAPABILITY ASSUMPTIONS: What model capabilities does this assume? "
        "Flag anything that requires capabilities beyond current reliable "
        "production use.\n\n"
        "Mandatory: at least one approach per process must be simpler than "
        "you think it should be. The simplest approach that works is usually "
        "right -- and if it's not right, understanding why it's not right "
        "clarifies what the complexity is actually buying."
    )
    Meta = (
        "The first design idea is rarely the best, but agents anchor on it "
        "heavily. Requiring 2-3 structurally different approaches forces "
        "genuine exploration of the design space. The mandatory 'simpler "
        "than seems right' option prevents complexity bias -- often the "
        "simple version turns out to be sufficient."
    )
    Uses = [high_achiever_bar]
    Requires = [SnippetRole("landscape_intelligence")]


class SelectDesign(Op):
    """Convergent -- evaluate trade-offs and commit to an approach."""

    Input = DesignOptions
    Output = SelectedDesigns
    Intent = (
        "For each process, evaluate the design options and select one.\n\n"
        "Evaluate every option on four criteria:\n"
        "1. RELIABILITY: Which fails least often? Which recovers best when "
        "it does fail? Consider both the steady-state failure rate and the "
        "tail-risk scenarios.\n"
        "2. SIMPLICITY: Fewer moving parts means fewer failure modes, less "
        "coordination, and easier debugging. Count the agents, Ops, "
        "connections, and external dependencies for each option.\n"
        "3. OBSERVABILITY: Can you tell when it's working correctly vs "
        "silently producing wrong output? What metrics or checks would "
        "you use? An approach that looks like it's working when it isn't "
        "is worse than one that fails loudly.\n"
        "4. EVOLVABILITY: When model capabilities improve in 6 months, "
        "does this design get better automatically (because it's structured "
        "as orchestration) or does it need a rewrite (because capabilities "
        "are hardcoded into the structure)?\n\n"
        "For each process output:\n"
        "- CHOSEN: Approach name and the specific reasons it won on the "
        "four criteria above.\n"
        "- REJECTED: For each rejected approach, the specific reason it "
        "lost -- not 'it was worse' but which criterion it failed on and why.\n"
        "- OPEN RISKS: Known risks accepted with this choice. What would "
        "make you revisit this decision?"
    )
    Meta = (
        "Without explicit evaluation criteria, agents pick whatever sounds "
        "most impressive or comprehensive. The four criteria (reliability, "
        "simplicity, observability, evolvability) encode the values that "
        "matter for agent-based systems. Requiring rejection reasons prevents "
        "post-hoc rationalization and creates a decision record for when "
        "assumptions change."
    )
    Uses = [decision_journal, simplicity_bias]


# ---------------------------------------------------------------------------
# Diamond 3: WHO/WHAT does the work?
# ---------------------------------------------------------------------------

class DecomposeAgents(Op):
    """Divergent -- explore agent boundary options."""

    Input = SelectedDesigns
    Output = AgentOptions
    Intent = (
        "For each selected process design, brainstorm how to divide the work "
        "across agents. Generate at least 2 structurally different splits.\n\n"
        "For each split option, define:\n"
        "- AGENTS: List each agent with name, responsibility, and scope. One "
        "sentence per agent -- if you need more, the agent is doing too much.\n"
        "- DATA FLOWS: What data passes between agents? Be specific about "
        "format and content, not just 'sends results.'\n"
        "- FAILURE PROPAGATION: If agent B depends on agent A, what happens "
        "when A produces bad output? Does B detect it, propagate the error, "
        "or silently continue with garbage?\n"
        "- TRUST BOUNDARIES: Which agents need access to sensitive data? The "
        "agent that reads customer data shouldn't also have write access to "
        "billing. Map where trust boundaries align with agent boundaries.\n"
        "- COMMUNICATION: Do agents operate independently (fan-out/fan-in), "
        "conversationally (teammate pattern), or in strict sequence (pipeline)?\n\n"
        "Consider the spectrum from one monolithic agent (simpler coordination, "
        "harder to debug) to many specialist agents (clearer responsibility, "
        "more coordination overhead). The right answer depends on the process."
    )
    Meta = (
        "Agent boundaries are the most consequential architecture decision -- "
        "they determine failure isolation, trust separation, and coordination "
        "cost. Exploring multiple splits before committing prevents anchoring "
        "on the first decomposition. The trust boundary requirement catches "
        "security issues that emerge from agent boundaries, not just "
        "functional ones."
    )
    Uses = [failure_mode_forcing, simplicity_bias]


class DefineAgents(Op):
    """Convergent -- lock agent definitions as Op library specs."""

    Input = AgentOptions
    Output = AgentDefinitions
    Intent = (
        "Select the best agent split for each process and lock the agent "
        "definitions. Each definition must be specific enough to build an "
        "Op library from directly.\n\n"
        "For each agent, provide:\n"
        "- NAME: Clear, specific. Not 'ProcessAgent' -- name it for what it "
        "actually does.\n"
        "- PURPOSE: One sentence. If you need two sentences, this agent is "
        "doing two things.\n"
        "- OWNED PROCESSES: Which processes from the scoped list this agent "
        "is responsible for.\n"
        "- OPS: Decompose into thought steps (not tasks). Each Op should be "
        "one focused cognitive action describable in one sentence: a judgment, "
        "a classification, a draft, a comparison. If you write 'analyze and "
        "then synthesize,' that's two Ops.\n"
        "- INPUTS/OUTPUTS: What Concept types does this agent consume and "
        "produce? Name them concretely.\n"
        "- CONNECTIONS: What other agents does it send to or receive from? "
        "What data, in what direction, triggered by what?\n"
        "- HUMAN CHECKPOINTS: Which decisions require human approval before "
        "proceeding? Default to more checkpoints, not fewer.\n"
        "- QUALITY BAR: What does 'good output' look like? Specific enough "
        "to evaluate -- 'high quality' means nothing. 'Every recommendation "
        "cites evidence and states confidence level' is evaluable."
    )
    Meta = (
        "This is where the architecture solidifies -- each agent definition "
        "becomes an Op library spec. The requirement to decompose into "
        "thought steps (not tasks) catches the most common design mistake: "
        "agents that are too broad. The quality bar requirement prevents "
        "vague 'good output' specifications that can't be evaluated."
    )
    Uses = [high_achiever_bar, decision_journal]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class FailureAnalysis(Op):
    """Divergent -- adversarially explore how each component breaks."""

    Input = AgentDefinitions
    Output = FailureModes
    Intent = (
        "For each agent and each inter-agent connection in the architecture, "
        "conduct an adversarial failure analysis.\n\n"
        "For each component, answer:\n"
        "1. WRONG OUTPUT: What happens when this agent produces incorrect "
        "output? Not 'it could be wrong' -- describe the specific failure. "
        "A classifier that mislabels, a synthesizer that hallucinates, a "
        "router that sends to the wrong branch.\n"
        "2. DETECTION: Who notices the failure? How long until they notice? "
        "If the answer is 'nobody notices for days,' that's the most "
        "dangerous failure mode.\n"
        "3. BLAST RADIUS: Does one agent's failure cascade to others? Map "
        "the propagation path. If agent A fails and agents B, C, D all "
        "consume A's output, all four are affected.\n"
        "4. RECOVERY: What's the recovery path? Retry, escalate to human, "
        "abort the process, or fall back to a simpler approach? Does the "
        "recovery path itself have failure modes?\n"
        "5. UNSUPERVISED WORST CASE: If this runs without human oversight "
        "for a week, what's the worst outcome? This is the scenario that "
        "determines whether human checkpoints are in the right places.\n\n"
        "Be adversarial. Focus on the failures that would be embarrassing "
        "or costly -- the ones that make you say 'we should have thought "
        "of that.' Don't just list plausible failures -- imagine the ones "
        "a motivated red team would find."
    )
    Meta = (
        "If you haven't described how it breaks, you haven't designed it. "
        "Agents tend to produce optimistic failure analyses ('it might "
        "occasionally be wrong') rather than adversarial ones. The structured "
        "questions force specificity. The 'unsupervised for a week' scenario "
        "is the most reliable test of whether human checkpoints are correctly "
        "placed."
    )
    Uses = [failure_mode_forcing, reality_check]


class GapCheck(Op):
    """Divergent -- find what the design missed or assumed without checking."""

    Input = AgentDefinitions
    Output = DesignGaps
    Intent = (
        "Review the full architecture and look for what's missing, broken, "
        "or assumed without evidence.\n\n"
        "Check each category:\n"
        "1. MISSING PROCESSES: Are there real-world processes that exist but "
        "aren't represented in the architecture? What happens at the edges "
        "of the designed system -- where does work enter and leave?\n"
        "2. HANDOFF RISKS: At every point where data moves between agents, "
        "could it get lost, corrupted, or misinterpreted? What if the "
        "format changes? What if the upstream agent changes its output "
        "without the downstream agent knowing?\n"
        "3. CAPABILITY ASSUMPTIONS: What model capabilities does the design "
        "assume? Flag anything that depends on capabilities beyond current "
        "reliable production use. 'Reliable' means works 95%+ of the time, "
        "not 'works in demos.'\n"
        "4. TRUST BOUNDARIES: Are security/trust boundaries enforced by "
        "agent separation, or just by policy? Policy-only boundaries will "
        "be violated.\n"
        "5. MONITORING GAPS: For each agent, can you tell whether it's "
        "working correctly, partially wrong, or completely broken? If you "
        "can't distinguish between these states from the outside, that's "
        "a monitoring gap.\n\n"
        "Also identify:\n"
        "- UNVERIFIED ASSUMPTIONS: What does the design take for granted "
        "that hasn't been validated? (Data availability, user behavior, "
        "integration capabilities, team capacity.)\n"
        "- BREAKING CHANGES: What changes in the business would invalidate "
        "this architecture? (New regulation, 10x scale, product pivot, "
        "key integration going away.)"
    )
    Meta = (
        "This is CheckBlindspots for architecture. The primary design steps "
        "focus on what's being built -- this step asks what's not being "
        "built. Without it, designs tend to have clean internal logic but "
        "miss the messy edges where the system meets reality. The "
        "'unverified assumptions' and 'breaking changes' sections catch "
        "the most common post-deployment surprises."
    )
    Uses = [reality_check]
    Requires = [SnippetRole("landscape_intelligence")]


class CompileSpecs(Op):
    """Convergent -- assemble final Op library specs from all upstream work."""

    Input = AgentDefinitions
    Output = OpLibrarySpecs
    Intent = (
        "Compile the final Op library specification for each agent, "
        "incorporating feedback from failure analysis and gap checks.\n\n"
        "For each agent, produce a self-contained spec with:\n"
        "- AGENT NAME and PURPOSE (one sentence).\n"
        "- CONCEPTS: List every input/output type with name and description. "
        "Concepts should carry enough description for an LLM prompt but not "
        "so much that they over-constrain the data shape.\n"
        "- OPS: For each Op, provide name, Intent (specific -- what to think "
        "about, what criteria matter, what shape the output takes), and Meta "
        "(why this Op exists, what approach it takes). Each Op should be one "
        "cognitive step.\n"
        "- SNIPPETS: Guardrails, quality criteria, domain rules that should "
        "be injected into Op prompts. Extract recurring constraints from "
        "Intents into reusable Snippets.\n"
        "- TOOLS: Programmatic functions needed (lookups, calculations, API "
        "calls). For each: name, description, parameters.\n"
        "- COMPOSITION: How Ops connect -- express as a tree using sequence, "
        "gather, branch_on, and loop. Note which steps can run in parallel.\n"
        "- INTERCONNECTIONS: What this agent sends to / receives from other "
        "agents, including data format and triggering conditions.\n\n"
        "Each spec must be complete enough to build the Op library without "
        "referring back to earlier design steps. If a detail is ambiguous, "
        "make a concrete choice and document it -- don't leave it open."
    )
    Meta = (
        "This is primarily a compilation and structuring step -- gathering "
        "decisions made in earlier Ops into a buildable format. It does "
        "require judgment to resolve ambiguities and extract Snippets from "
        "repeated patterns, but the core design decisions are already made. "
        "The 'self-contained' requirement ensures specs don't rely on "
        "context that won't be available when someone builds from them."
    )
    Uses = [high_achiever_bar]


# ---------------------------------------------------------------------------
# Composition: the full design flow
# ---------------------------------------------------------------------------

class DesignBusinessAgents(Op):
    """Entry point -- double-diamond design flow for agent-based systems."""

    Input = BusinessContext
    Output = OpLibrarySpecs
    Intent = (
        "Design agent-based processes for a business or system using a "
        "three-diamond structure: first discover what processes exist, then "
        "design how each should work, then define which agents do the work. "
        "Validate with failure analysis and gap checking before compiling "
        "final Op library specs."
    )
    Meta = (
        "Three-diamond flow: diverge/converge on process scope, "
        "diverge/converge on design approach, diverge/converge on agent "
        "architecture, then validate. The validation steps (FailureAnalysis "
        "and GapCheck) run in parallel because they examine the same input "
        "from independent angles -- failure modes vs missing pieces. "
        "CompileSpecs runs last to incorporate findings from both."
    )
    body = sequence(
        # Diamond 1: WHAT processes exist?
        BroadScan,
        PrioritizeScope,
        # Diamond 2: HOW should each process work?
        ExploreDesigns,
        SelectDesign,
        # Diamond 3: WHO/WHAT does the work?
        DecomposeAgents,
        DefineAgents,
        # Validation (parallel -- independent lenses on same input)
        gather(FailureAnalysis, GapCheck),
        # Compile final specs
        CompileSpecs,
    )
    entry = True
