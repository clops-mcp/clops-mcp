# Business Org & Process Designer — Flow Sketch

A general-purpose flow for architecting agent-based systems. Works for businesses, products, teams, or any complex system where processes need to be decomposed into agents and Ops.

The output isn't a document — it's Op library specs that agents can build from directly.

## Double Diamond Structure

```
Diamond 1: WHAT processes exist?
  DIVERGE: BroadScan         — surface all possible processes, including ones nobody's named yet
  CONVERGE: PrioritizeScope  — select what to design now vs defer

Diamond 2: HOW should each process work?
  DIVERGE: ExploreDesigns    — for each process, generate 2-3 fundamentally different approaches
  CONVERGE: SelectDesign     — evaluate trade-offs, pick the approach, document why

Diamond 3: WHO/WHAT does the work?
  DIVERGE: DecomposeAgents   — brainstorm agent boundaries, roles, what could be combined or split
  CONVERGE: DefineAgents     — lock agent definitions, Ops per agent, interconnections

Validation:
  FailureAnalysis            — how does each process break? what's the blast radius?
  GapCheck                   — what's missing? what did we assume without checking?
  CompileSpecs               — produce Op library specs per agent
```

## Ops (rough)

### Diamond 1: Scoping

**BroadScan** (divergent)
```
Input: BusinessContext
Output: ProcessLandscape
Meta: "Agents converge too fast. This step forces broad exploration before any decisions."
Intent: |
  You are given a description of a business/system. Before narrowing anything,
  map the full landscape of processes — both the obvious ones and the ones
  nobody's named yet.

  For each process identified:
  - What triggers it? (user action, schedule, another process, external event)
  - Who cares about the output? (customer, internal team, another system)
  - What happens if it doesn't run? (nothing? revenue loss? safety issue?)
  - Is this actually one process or multiple wearing one name?

  Push past the first 5-6 obvious ones. What processes exist in the gaps
  between the obvious ones? What happens at handoff points? What's manual
  today that nobody thinks of as a "process"?
```

**PrioritizeScope** (convergent)
```
Input: ProcessLandscape
Output: ScopedProcesses
Meta: "Not everything should be designed at once. This forces explicit prioritization."
Intent: |
  Given the full process landscape, select which processes to design now.

  Criteria:
  - Impact: which processes matter most to the business outcome?
  - Feasibility: which can actually be agent-driven today vs need capabilities
    that don't exist yet?
  - Dependencies: which processes must exist before others can work?

  Output: a prioritized list with rationale. For each deferred process,
  note what would need to change for it to move up. Be specific about
  what "high impact" means — revenue, time saved, error reduction, etc.
  Not just "this is important."
```

### Diamond 2: Design

**ExploreDesigns** (divergent)
```
Input: ScopedProcesses
Output: DesignOptions
Meta: "The first design idea is rarely the best. This forces 2-3 alternatives per process."
Intent: |
  For each scoped process, generate 2-3 fundamentally different approaches.
  Not variations on one theme — structurally different designs.

  For each approach:
  - What's the core idea? (one sentence)
  - What's automated vs human-in-the-loop?
  - Where does it use LLM reasoning vs programmatic tools?
  - What's the main risk?
  - What model capability does it assume?

  Include at least one approach that's simpler than you think it should be.
  The simplest approach that works is usually right.
```

**SelectDesign** (convergent)
```
Input: DesignOptions
Output: SelectedDesigns
Meta: "Evaluation criteria must be explicit or agents pick whatever sounds best."
Intent: |
  For each process, evaluate the design options and select one.

  Evaluate on:
  - Reliability: which fails least? Which recovers best when it does fail?
  - Simplicity: fewer moving parts = fewer failure modes
  - Observability: can you tell when it's working vs silently wrong?
  - Evolvability: when the model gets better in 6 months, does this design
    get better automatically or need a rewrite?

  Document the decision AND the reasons the other options were rejected.
  "We chose X because..." and "We didn't choose Y because..." —
  both matter for future context.
```

### Diamond 3: Agent Architecture

**DecomposeAgents** (divergent)
```
Input: SelectedDesigns
Output: AgentOptions
Meta: "Agent boundaries are the most consequential architecture decision. Explore before committing."
Intent: |
  For each selected process design, brainstorm how to divide the work
  across agents. Consider multiple splits:

  - One agent owns the whole process vs multiple agents with handoffs
  - Specialist agents (each does one thing well) vs generalist agents
    (fewer agents, more capability each)
  - Where do agent boundaries align with trust boundaries?
    (the agent that reads customer data shouldn't also have write access
    to billing)

  For each split option, identify:
  - What data flows between agents?
  - What happens when an agent in the middle fails?
  - Which agents need to talk to each other vs operate independently?
```

**DefineAgents** (convergent)
```
Input: AgentOptions
Output: AgentDefinitions
Meta: "This is where the architecture solidifies. Each agent definition becomes an Op library spec."
Intent: |
  Lock the agent definitions. For each agent:

  - Name and one-sentence purpose
  - What processes it owns
  - What Ops it needs (decompose into thought steps per the philosophy)
  - What data it consumes and produces
  - What other agents it connects to and how
  - What human checkpoints exist
  - What its quality bar is — what does "good output" look like?

  Each agent definition should be specific enough that someone could
  build the Op library from this spec alone.
```

### Validation

**FailureAnalysis** (divergent — exploring what breaks)
```
Input: AgentDefinitions
Output: FailureModes
Meta: "If you haven't described how it breaks, you haven't designed it."
Intent: |
  For each agent and each inter-agent connection:

  - What happens when this agent produces wrong output?
  - Who notices? How long until they notice?
  - What's the blast radius? Does one agent's failure cascade?
  - What's the recovery path? Retry? Escalate to human? Abort?
  - What's the worst case if this runs unsupervised for a week?

  Be adversarial. Don't just list plausible failures — imagine the
  failures that would be embarrassing or costly. The ones where you'd
  say "we should have thought of that."
```

**GapCheck** (divergent — what's missing)
```
Input: AgentDefinitions
Output: DesignGaps
Meta: "CheckBlindspots for architecture. What did the design assume without verifying?"
Intent: |
  Review the full architecture and look for:

  - Processes that exist in reality but aren't represented
  - Handoffs between agents where data could get lost or corrupted
  - Assumptions about model capability that might not hold
  - Security/trust boundaries that aren't enforced by agent separation
  - Monitoring gaps — parts of the system where you can't tell if
    it's working or silently failing

  Also: what did we assume about the business that we didn't verify?
  What changes in the business would break this architecture?
```

**CompileSpecs** (convergent — probably programmatic)
```
Input: everything upstream
Output: OpLibrarySpecs
Meta: "This is a compilation step, not a reasoning step. Could be a programmatic tool."
Intent: |
  For each agent, compile the final Op library spec:

  - Agent name and purpose
  - Concepts (input/output types)
  - Ops (with Intent and Meta for each)
  - Snippets (guardrails, quality criteria)
  - Tools (programmatic functions needed)
  - Composition (how Ops connect — sequence, gather, branch, loop)
  - Interconnections (what this agent sends to / receives from other agents)

  Output structured specs that can be handed directly to the
  clops-authoring skill to build.
```

## Snippets Needed

- `high_achiever_bar` — force "great vs adequate" articulation for every decision
- `failure_mode_forcing` — every component must describe how it breaks
- `reality_check` — theory vs actual behavior gap analysis
- `simplicity_bias` — prefer fewer moving parts; justify complexity
- `decision_journal` — document not just what was chosen but what was rejected and why

## Open Questions

1. Should each diamond be a separate flow (composable) or one monolithic flow?
2. How do we handle iteration? The first pass will be wrong — how does the user feed back "this agent boundary is wrong, try again" without restarting everything?
3. How does this connect to the session_analyzer? After the agents are built and running, the analyzer should validate that the architecture is working as designed.
4. Should CompileSpecs produce actual Python files (concepts.py, ops.py) or just structured specs that a human/agent translates?
