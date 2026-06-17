from clops import Op
from smoke_03_tool_use.concepts import PersonName, PersonRecord
from smoke_03_tool_use.tools import lookup_age


class LookupReport(Op):
    Input = PersonName
    Output = PersonRecord
    Intent = (
        "You are given a person's first name. Use the `lookup_age` tool to retrieve "
        "their age, then return a one-sentence record of the form "
        "'<Name> is <age> years old.' If the tool returns age=None, return "
        "'<Name> is not in the directory.'"
    )
    Meta = (
        "Validates that an Op can declare and invoke a tool during execution. "
        "Demonstrates the Tools field and the tool-call/tool-result round trip."
    )
    Tools = [lookup_age]
    entry = True
