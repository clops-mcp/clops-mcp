from clops import Op, loop, sequence
from smoke_06_loop.concepts import Benefits, Topic


class Seed(Op):
    Input = Topic
    Output = Benefits
    Intent = (
        "Produce an initial bulleted list of 1-2 benefits for the given topic. "
        "Do NOT append [done] — refinement passes will add more benefits."
    )
    Meta = (
        "Provides the initial seed value for a loop pattern. Kept minimal so "
        "the iterative Refine step has room to grow the list incrementally."
    )


class Refine(Op):
    Input = Benefits
    Output = Benefits
    Intent = (
        "Take the existing list of benefits and add ONE more distinct benefit "
        "that isn't already present. Return the full updated list. If the "
        "list now contains 5 or more distinct benefits, append the literal "
        "marker [done] on its own line so the loop terminates. Otherwise, "
        "do not include [done]."
    )
    Meta = (
        "Demonstrates the loop body pattern: accepts and returns the same type, "
        "with a sentinel marker that the loop's `until` predicate can detect."
    )


class Brainstorm(Op):
    Input = Topic
    Output = Benefits
    Intent = "Seed an initial benefits list, then refine until at least 5 benefits."
    Meta = (
        "Composite entry Op that wires sequence + loop together, demonstrating "
        "how a seed-then-iterate pattern composes in clops."
    )
    body = sequence(
        Seed,
        loop(
            body=Refine,
            until=lambda output: "[done]" in str(output),
            max_iterations=8,
        ),
    )
    entry = True
