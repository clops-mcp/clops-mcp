from clops import Op, gather, sequence
from smoke_13_gather_subroutine.concepts import Angle, Brief, Definition, Term, Topic


class Setup(Op):
    Input = Topic
    Output = Topic
    Intent = (
        "Restate the topic clearly in one sentence. Do not add analysis. "
        "This is a pass-through to set up the parallel research phase."
    )
    Meta = (
        "Identity pass-through Op that normalizes input before a gather fan-out."
    )


class DefineTerm(Op):
    Input = Term
    Output = Definition
    Intent = (
        "Define the given technical term in a single plain-language sentence "
        "for a non-expert reader. Output only the definition."
    )
    Meta = (
        "Leaf sub-Op invoked dynamically (call_tool) by a gather branch. "
        "Demonstrates that a single branch can delegate mid-turn while its "
        "peer branches run concurrently and the join order is preserved."
    )


class TechnicalAngle(Op):
    Input = Topic
    Output = Angle
    Intent = (
        "Analyze the topic from a technical / infrastructure perspective in one "
        "paragraph (2-4 sentences). FIRST, pick the single most important "
        "technical term in the topic and call the `DefineTerm` capability "
        "(via call_tool) to get a plain-language definition of it. THEN write "
        "your paragraph, opening with that definition so a non-expert can follow."
    )
    Meta = (
        "Gather branch that makes a dynamic sub-Op call. The branch suspends "
        "while DefineTerm runs, then is re-dispatched with the definition under "
        "a 'Result from DefineTerm' section — all underneath the live gather."
    )
    Tools = [DefineTerm]


class EconomicAngle(Op):
    Input = Topic
    Output = Angle
    Intent = (
        "Write one paragraph (2-4 sentences) analyzing the topic purely from "
        "an economic / cost-benefit perspective. Stay within this angle."
    )
    Meta = (
        "Plain peer gather branch (no subroutine). Completes normally while the "
        "TechnicalAngle branch is mid-subroutine, exercising partial suspension."
    )


class Synthesize(Op):
    Input = Angle  # loose — actual input is a list of two Angle outputs
    Output = Brief
    Intent = (
        "You are given a list of two paragraphs (technical, economic). "
        "Synthesize them into a single coherent brief of 3-5 sentences. "
        "Cite each angle at least once."
    )
    Meta = (
        "Fan-in step after gather: receives the collected list of parallel "
        "outputs and merges them into a single coherent result."
    )


class ResearchBrief(Op):
    Input = Topic
    Output = Brief
    Intent = (
        "Restate the topic, research a technical and an economic angle in "
        "parallel (the technical angle defines its key term via a sub-Op), "
        "then synthesize into a brief."
    )
    Meta = (
        "Composite entry Op wiring sequence + gather where one branch makes a "
        "dynamic call. Exercises Slice 3: dynamic calls inside gather branches."
    )
    body = sequence(
        Setup,
        gather(TechnicalAngle, EconomicAngle),
        Synthesize,
    )
    entry = True
