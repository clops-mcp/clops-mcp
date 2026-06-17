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
