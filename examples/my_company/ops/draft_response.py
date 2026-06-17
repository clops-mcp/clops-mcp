from clops import Op, SnippetRole
from examples.my_company.concepts import Intent, Response
from examples.my_company.snippets import safety_rules


class DraftResponse(Op):
    Input = Intent
    Output = Response
    Intent = (
        "Draft a customer-facing response given a classified intent. "
        "Match brand voice; acknowledge before solving."
    )
    Meta = (
        "Drafts a response using the upstream classification as steering "
        "context. Requires brand_voice so every reply sounds on-brand. "
        "Kept as a separate leaf (rather than merging with ClassifyIntent) "
        "so each step can be independently tested and the pipeline can be "
        "extended with review or approval stages downstream."
    )
    Uses = [safety_rules]
    Requires = [SnippetRole("brand_voice")]
