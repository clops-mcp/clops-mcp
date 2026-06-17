from clops import Op, SnippetRole
from examples.my_company.concepts import Intent, UserMessage
from examples.my_company.snippets import safety_rules
from examples.my_company.tools import query_customer_history


class ClassifyIntent(Op):
    Input = UserMessage
    Output = Intent
    Intent = (
        "Classify a customer support message into one of three categories: "
        "billing, technical, or general. Look at the message content and, "
        "if helpful, consult the customer's recent history to disambiguate."
    )
    Meta = (
        "A single-pass classifier leaf Op. Uses tool access to customer "
        "history so the LLM can disambiguate borderline cases (e.g. a "
        "'charge' complaint that could be billing or technical). We chose "
        "a flat three-category taxonomy to keep downstream routing simple; "
        "finer categories can be added by extending the Intent Concept."
    )
    Uses = [safety_rules]
    Requires = [SnippetRole("brand_voice")]
    Tools = [query_customer_history]
