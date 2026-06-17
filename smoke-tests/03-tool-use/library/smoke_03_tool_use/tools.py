from clops import Tool


_AGES = {"alice": 30, "bob": 42, "carol": 25}


def _lookup_age(name: str) -> dict:
    """Deterministic age lookup. Returns {'name': str, 'age': int|None}."""
    return {"name": name, "age": _AGES.get(name.lower())}


lookup_age = Tool(
    name="lookup_age",
    description=(
        "Look up a person's age by first name. Returns a dict "
        "{'name': <name>, 'age': <int or None if unknown>}."
    ),
    parameters={"name": str},
    handler=_lookup_age,
)
