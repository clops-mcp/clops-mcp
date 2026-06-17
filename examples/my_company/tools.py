from clops import Tool

query_customer_history = Tool(
    name="query_customer_history",
    description="Retrieve the last 10 support interactions for a customer.",
    parameters={"customer_id": str},
    handler=lambda customer_id: [],
)
