from clops import Snippet

safety_rules = Snippet(
    id="safety_rules",
    content=(
        "Never acknowledge account details the user hasn't already provided. "
        "Never recommend competitor products."
    ),
)

brand_voice = Snippet(
    id="brand_voice_default",
    role="brand_voice",
    content=(
        "Warm but efficient. First-person plural ('we'). No exclamation points. "
        "Acknowledge the problem before offering a solution."
    ),
)
