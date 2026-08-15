"""Concepts -- named, described handles for data flowing between Ops."""

from clops import Concept


class BusinessContext(Concept):
    description = (
        "A description of the business, product, team, or system to design "
        "agent-based processes for. Includes: what the organization does, who "
        "it serves, what outcomes matter, current pain points or bottlenecks, "
        "and any constraints (regulatory, technical, organizational). The more "
        "concrete the context, the better the downstream process discovery."
    )


class ProcessLandscape(Concept):
    description = (
        "A broad map of all processes identified in the business context -- "
        "both the obvious named ones and the hidden ones that exist in gaps, "
        "handoffs, and manual workarounds. Each process entry includes: name "
        "(str), trigger (what starts it), stakeholders (who cares about the "
        "output), failure_impact (what happens if it doesn't run), and "
        "sub_processes (list of constituent parts if the process is actually "
        "multiple processes wearing one name). The landscape is intentionally "
        "over-inclusive -- narrowing happens in the next step."
    )


class ScopedProcesses(Concept):
    description = (
        "A prioritized subset of the process landscape selected for design. "
        "Contains: selected_processes (ordered list, each with name, rationale "
        "for inclusion, and impact_type -- one of 'revenue', 'time_saved', "
        "'error_reduction', 'compliance', 'customer_experience'), "
        "deferred_processes (list, each with name and what_would_change -- "
        "specific conditions under which it should move up), and "
        "dependency_notes (which selected processes must exist before others "
        "can work)."
    )


class DesignOptions(Concept):
    description = (
        "For each scoped process, 2-3 structurally different design approaches. "
        "Each approach includes: process_name (str), approach_name (str), "
        "core_idea (one sentence), automation_level (what's automated vs "
        "human-in-the-loop), llm_vs_programmatic (where LLM reasoning is "
        "used vs deterministic tools), main_risk (str), and "
        "capability_assumptions (what model capabilities it depends on). "
        "At least one approach per process must be simpler than seems "
        "sufficient."
    )


class SelectedDesigns(Concept):
    description = (
        "The chosen design approach for each scoped process, with explicit "
        "evaluation rationale. Each entry includes: process_name (str), "
        "chosen_approach (str), rationale (why this one -- covering "
        "reliability, simplicity, observability, evolvability), "
        "rejected_approaches (list of {name, rejection_reason}), and "
        "open_risks (known risks accepted with this choice). The rejection "
        "reasons are as important as the selection reasons for future context."
    )


class AgentOptions(Concept):
    description = (
        "For each selected design, multiple ways to divide the work across "
        "agents. Each option includes: process_name (str), split_name (str), "
        "agents (list of {name, responsibility, scope}), data_flows "
        "(what passes between agents), failure_propagation (what happens "
        "when an agent in the middle fails), trust_boundaries (where data "
        "access should be separated), and communication_pattern (independent "
        "vs conversational vs handoff)."
    )


class AgentDefinitions(Concept):
    description = (
        "Locked agent definitions ready to become Op library specs. Each "
        "agent includes: name (str), purpose (one sentence), "
        "owned_processes (list[str]), ops (list of {name, thought_step -- "
        "one-sentence description of the cognitive action}), "
        "inputs (list of Concept names it consumes), "
        "outputs (list of Concept names it produces), "
        "connections (list of {target_agent, data_exchanged, direction}), "
        "human_checkpoints (list of decision points requiring approval), "
        "and quality_bar (what 'good output' looks like -- specific enough "
        "to evaluate against)."
    )


class FailureModes(Concept):
    description = (
        "Adversarial failure analysis for each agent and inter-agent "
        "connection. Each entry includes: component (agent name or "
        "connection name), failure_scenario (str), detection_method "
        "(who notices and how long until they notice), blast_radius "
        "(does it cascade? what else breaks?), recovery_path (retry, "
        "escalate, abort, or other), and worst_case_unsupervised (what "
        "happens if this runs unattended for a week). Focuses on "
        "embarrassing and costly failures, not just plausible ones."
    )


class DesignGaps(Concept):
    description = (
        "Blindspot analysis of the full architecture. Each gap includes: "
        "category (one of 'missing_process', 'handoff_risk', "
        "'capability_assumption', 'trust_boundary', 'monitoring_gap', "
        "'business_assumption'), description (str), evidence (what in the "
        "design reveals this gap), and severity ('high', 'medium', 'low'). "
        "Also includes: unverified_assumptions (list of things the design "
        "takes for granted that haven't been validated) and "
        "breaking_changes (business changes that would invalidate the "
        "architecture)."
    )


class OpLibrarySpecs(Concept):
    description = (
        "Complete Op library specifications for each agent, ready to implement "
        "as a clops Op library. Each spec includes: agent_name (str), "
        "purpose (str), concepts (list of {name, description}), "
        "ops (list of {name, intent, meta, input, output}), "
        "snippets (list of {id, content, role}), "
        "tools (list of {name, description, parameters}), "
        "composition (how Ops connect -- sequence, gather, branch, loop "
        "expressed as a tree), and interconnections (what this agent "
        "sends to / receives from other agents). Each spec should be "
        "self-contained enough to build the library without referring "
        "back to earlier design steps."
    )
