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


# ---- output_bulk_only ------------------------------------------------


def test_output_bulk_only_warns():
    """An Output of nothing but bulk puts pure payload on the relay."""
    from clops import Field

    class BulkOnly(Concept):
        description = "The characterised flows."
        flows = Field("the full flow records", bulk=True)

    class Characterise(Op):
        Input = M
        Output = BulkOnly
        Intent = "Characterise the flows."
        Meta = "Test fixture Op for validating output_bulk_only."

    result = LintResult()
    check_op(Characterise, result)
    assert result.ok  # a warning, not an error
    findings = [f for f in result.warnings if f.rule == "output_bulk_only"]
    assert len(findings) == 1
    assert "flows" in findings[0].message


def test_output_bulk_with_thin_companion_is_clean():
    from clops import Field

    class Manifest(Concept):
        description = "A manifest of the characterised flows."
        handle = Field("the handle holding the full records")
        flow_count = Field("how many records are behind the handle")
        flows = Field("the full flow records", bulk=True)

    class Characterise2(Op):
        Input = M
        Output = Manifest
        Intent = "Characterise the flows."
        Meta = "Test fixture Op for validating a thin companion field."

    result = LintResult()
    check_op(Characterise2, result)
    assert not [f for f in result.warnings if f.rule == "output_bulk_only"]


def test_output_without_fields_is_clean():
    """Fields are optional; a Concept with none must not trip the rule."""
    class NoFields(Op):
        Input = M
        Output = M
        Intent = "do a thing"
        Meta = "Test fixture Op for validating fieldless Outputs."

    result = LintResult()
    check_op(NoFields, result)
    assert not [f for f in result.warnings if f.rule == "output_bulk_only"]


# ---- Op subroutines in Tools -----------------------------------------


def test_op_subroutine_in_tools_is_not_an_error():
    """op.py accepts Op subclasses in Tools; the linter must agree."""
    class Subroutine(Op):
        Input = M
        Output = M
        Intent = "Do the sub-thing."
        Meta = "Test fixture Op used as a subroutine."

    class Caller(Op):
        Input = M
        Output = M
        Intent = "Do the thing, delegating part of it."
        Meta = "Test fixture Op that declares a subroutine."
        Tools = [Subroutine]

    result = LintResult()
    check_op(Caller, result)
    assert result.ok, [str(f) for f in result.findings]


def test_unregistered_op_subroutine_is_a_tool_integrity_error():
    class Ghost(Op):
        Input = M
        Output = M
        Intent = "Vanish."
        Meta = "Test fixture Op removed from the registry."

    class Caller2(Op):
        Input = M
        Output = M
        Intent = "Call the ghost."
        Meta = "Test fixture Op referencing an unregistered subroutine."
        Tools = [Ghost]

    from clops.registry import registry

    # Ops are keyed by qualified path; the bare-name multimap indexes them.
    for key, op in list(registry._ops.items()):
        if op is Ghost:
            del registry._ops[key]
            paths = registry._by_bare.get(Ghost.__name__)
            if paths and key in paths:
                paths.remove(key)

    result = LintResult()
    check_op(Caller2, result)
    assert any(f.rule == "tool_integrity" for f in result.errors)


def test_tools_type_error_names_both_accepted_shapes():
    class Bad2(Op):
        Input = M
        Output = M
        Intent = "x"
        Meta = "Test fixture Op with a junk Tools entry."

    Bad2.Tools = ["not a tool"]
    result = LintResult()
    check_op(Bad2, result)
    findings = [f for f in result.errors if f.rule == "tools_type"]
    assert len(findings) == 1
    assert "Tool instance or an Op subclass" in findings[0].message
