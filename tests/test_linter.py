import pytest

from clops import Concept, Op, Snippet, SnippetRole, Tool, sequence
from clops.linter import SNIPPET_SOFT_MAX, LintResult, Severity, check_all, check_op


class M(Concept):
    description = "m"


def test_clean_op_has_no_findings():
    safety = Snippet(id="s", content="be safe")

    class Good(Op):
        Input = M
        Output = M
        Intent = "do a thing"
        Meta = "Test fixture Op for validating clean lint."
        Uses = [safety]

    result = LintResult()
    check_op(Good, result)
    assert result.ok
    assert result.warnings == []


def test_snippet_size_warning():
    big = Snippet(id="big", content="x" * (SNIPPET_SOFT_MAX + 1))

    class UsesBig(Op):
        Input = M
        Output = M
        Intent = "x"
        Meta = "Test fixture Op for validating snippet size warning."
        Uses = [big]

    result = LintResult()
    check_op(UsesBig, result)
    assert any(f.rule == "snippet_size" for f in result.warnings)


def test_requires_resolution_warning():
    class NeedsRole(Op):
        Input = M
        Output = M
        Intent = "x"
        Meta = "Test fixture Op for validating requires resolution."
        Requires = [SnippetRole("missing_role")]

    result = check_all()
    assert any(
        f.rule == "requires_resolution" and f.severity is Severity.WARNING
        for f in result.findings
    )


def test_requires_resolution_satisfied_when_role_present():
    Snippet(id="bv", role="brand_voice", content="warm")

    class HasRole(Op):
        Input = M
        Output = M
        Intent = "x"
        Meta = "Test fixture Op for validating satisfied requires."
        Requires = [SnippetRole("brand_voice")]

    result = check_all()
    assert not any(f.rule == "requires_resolution" for f in result.findings)


def test_body_integrity_checked():
    class Leaf(Op):
        Input = M
        Output = M
        Intent = "l"
        Meta = "Test fixture Op for validating body integrity."

    class Parent(Op):
        Input = M
        Output = M
        Intent = "p"
        Meta = "Test fixture Op for validating body integrity."
        body = sequence(Leaf)

    result = LintResult()
    check_op(Parent, result)
    assert result.ok


def test_tool_integrity_error_when_unregistered():
    tool = Tool(name="t", description="d")

    class UsesTool(Op):
        Input = M
        Output = M
        Intent = "x"
        Meta = "Test fixture Op for validating tool integrity."
        Tools = [tool]

    from clops.registry import registry

    del registry._tools[tool.name]

    result = LintResult()
    check_op(UsesTool, result)
    assert any(f.rule == "tool_integrity" for f in result.errors)


def test_uses_type_error():
    class Bad(Op):
        Input = M
        Output = M
        Intent = "x"
        Meta = "Test fixture Op for validating Uses type checking."
        Uses = ["not a snippet"]

    result = LintResult()
    check_op(Bad, result)
    assert any(f.rule == "uses_type" for f in result.errors)


# ---- Op subroutines in Tools -----------------------------------------


def test_op_subroutine_in_tools_is_not_an_error():
    """`Tools` accepts Op classes as subroutine references — the metaclass
    allows them and the runtime resolves them through call_op. The linter
    used to flag every one of them as an error."""

    class Helper(Op):
        Input = M
        Output = M
        Intent = "help"
        Meta = "Test fixture Op used as a subroutine."

    class Caller(Op):
        Input = M
        Output = M
        Intent = "call a subroutine"
        Meta = "Test fixture Op declaring an Op subroutine in Tools."
        Tools = [Helper]

    result = LintResult()
    check_op(Caller, result)
    assert result.ok, [str(f) for f in result.errors]


def test_op_subroutine_in_tools_must_be_registered():
    class Ghost(Op):
        Input = M
        Output = M
        Intent = "vanish"
        Meta = "Test fixture Op removed from the registry."

    class Caller2(Op):
        Input = M
        Output = M
        Intent = "call a missing subroutine"
        Meta = "Test fixture Op declaring an unregistered subroutine."
        Tools = [Ghost]

    from clops.registry import registry

    for qpath, op_cls in list(registry._ops.items()):
        if op_cls is Ghost:
            del registry._ops[qpath]
            registry._by_bare.get(Ghost.__name__, []).remove(qpath)

    result = LintResult()
    check_op(Caller2, result)
    assert any(f.rule == "tool_op_reference" for f in result.errors)


def test_tools_type_error_for_neither_tool_nor_op():
    class Bad2(Op):
        Input = M
        Output = M
        Intent = "x"
        Meta = "Test fixture Op with a junk Tools entry."

    Bad2.Tools = ["not-a-tool"]

    result = LintResult()
    check_op(Bad2, result)
    assert any(f.rule == "tools_type" for f in result.errors)
