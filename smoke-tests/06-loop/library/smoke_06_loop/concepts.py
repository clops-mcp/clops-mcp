from clops import Concept


class Topic(Concept):
    description = "A short topic to brainstorm benefits for."


class Benefits(Concept):
    description = (
        "A bulleted list of benefits for the topic. The list grows over loop "
        "iterations. When the author judges the list to be complete (target: "
        "5 or more distinct benefits), the literal marker [done] MUST be "
        "appended to the end of the output. The loop terminates as soon as "
        "[done] appears anywhere in the output."
    )
