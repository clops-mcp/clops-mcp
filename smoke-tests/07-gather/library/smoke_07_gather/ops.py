from clops import Op, gather, sequence
from smoke_07_gather.concepts import Angle, Brief, Topic


class Setup(Op):
    Input = Topic
    Output = Topic
    Intent = (
        "Restate the topic clearly in one sentence. Do not add analysis. "
        "This is a pass-through to set up the parallel research phase."
    )
    Meta = (
        "Identity pass-through Op that normalizes input before a gather fan-out. "
        "Demonstrates that sequence steps can reshape data without changing type."
    )


class EconomicAngle(Op):
    Input = Topic
    Output = Angle
    Intent = (
        "Write one paragraph (2-4 sentences) analyzing the topic purely from "
        "an economic / cost-benefit perspective. Stay within this angle."
    )
    Meta = (
        "One of three parallel gather branches, each scoped to a single analytical "
        "lens. Demonstrates that gather fans out identical input to independent Ops."
    )


class SocialAngle(Op):
    Input = Topic
    Output = Angle
    Intent = (
        "Write one paragraph (2-4 sentences) analyzing the topic purely from "
        "a social / human perspective. Stay within this angle."
    )
    Meta = (
        "Second parallel gather branch. Same Input/Output shape as its siblings, "
        "differing only in the analytical angle specified by Intent."
    )


class TechnicalAngle(Op):
    Input = Topic
    Output = Angle
    Intent = (
        "Write one paragraph (2-4 sentences) analyzing the topic purely from "
        "a technical / infrastructure perspective. Stay within this angle."
    )
    Meta = (
        "Third parallel gather branch. Completes the fan-out trio, proving "
        "gather can run three independent Ops concurrently."
    )


class Synthesize(Op):
    Input = Angle  # loose — actual input is a list of three Angle outputs
    Output = Brief
    Intent = (
        "You are given a list of three paragraphs, each from a different "
        "angle (economic, social, technical). Synthesize them into a single "
        "coherent brief of 3-5 sentences. Cite each angle at least once."
    )
    Meta = (
        "Fan-in step after gather: receives the collected list of parallel "
        "outputs and merges them into a single coherent result."
    )


class ResearchBrief(Op):
    Input = Topic
    Output = Brief
    Intent = "Restate the topic, research three angles in parallel, synthesize into a brief."
    Meta = (
        "Composite entry Op that wires sequence + gather, demonstrating the "
        "fan-out / fan-in pattern: setup -> parallel angles -> synthesize."
    )
    body = sequence(
        Setup,
        gather(EconomicAngle, SocialAngle, TechnicalAngle),
        Synthesize,
    )
    entry = True
