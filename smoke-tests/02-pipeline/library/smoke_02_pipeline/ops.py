from clops import Op, sequence
from smoke_02_pipeline.concepts import Phrase


class Capitalize(Op):
    Input = Phrase
    Output = Phrase
    Intent = (
        "Convert the input phrase to UPPERCASE. Return only the uppercased text — "
        "no commentary, no punctuation changes, no rephrasing."
    )
    Meta = (
        "Atomic transform step in a pipeline — demonstrates a single-responsibility Op "
        "that can be composed via sequence."
    )


class Exclaim(Op):
    Input = Phrase
    Output = Phrase
    Intent = (
        "Append exactly three exclamation marks ('!!!') to the end of the input phrase. "
        "Do not change anything else about the phrase."
    )
    Meta = (
        "Second atomic transform in the pipeline — proves that sequence passes the output "
        "of one Op as the input to the next."
    )


class LoudIfy(Op):
    Input = Phrase
    Output = Phrase
    Intent = "Make the phrase loud: capitalize it, then add three exclamation marks."
    Meta = (
        "Composite Op that chains Capitalize then Exclaim via sequence — validates that "
        "the sequence combinator wires child Ops together correctly."
    )
    body = sequence(Capitalize, Exclaim)
    entry = True
