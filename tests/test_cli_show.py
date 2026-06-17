"""Tests for `clops show`."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clops import Concept, Op, Snippet, SnippetRole, Tool, branch_on, gather, loop, sequence
from clops.cli.show import run
from clops.combinators import describe


# ---- describe() structural output ----------------------------------


class _M(Concept):
    description = "m"


class _R(Concept):
    description = "r"


def test_describe_yields_sequence_with_children(_clean_registry_fixture=None):
    class A(Op):
        Input = _M
        Output = _R
        Intent = "a"
        Meta = "Test fixture Op for validating describe."

    class B(Op):
        Input = _R
        Output = _R
        Intent = "b"
        Meta = "Test fixture Op for validating describe."

    tree = list(describe(sequence(A, B)))
    assert tree == [
        (0, "sequence"),
        (1, "A"),
        (1, "B"),
    ]


def test_describe_yields_branch_on_with_arm_keys():
    class A(Op):
        Input = _M
        Output = _R
        Intent = "a"
        Meta = "Test fixture Op for validating branch_on describe."

    class B(Op):
        Input = _R
        Output = _R
        Intent = "b"
        Meta = "Test fixture Op for validating branch_on describe."

    tree = list(describe(branch_on(key=lambda _: "x", arms={"x": A, "y": B})))
    assert tree[0] == (0, "branch_on")
    labels = [label for _, label in tree]
    assert "'x':" in labels
    assert "'y':" in labels
    assert "A" in labels
    assert "B" in labels


def test_describe_gather_and_loop():
    class A(Op):
        Input = _M
        Output = _R
        Intent = "a"
        Meta = "Test fixture Op for validating gather and loop describe."

    class B(Op):
        Input = _R
        Output = _R
        Intent = "b"
        Meta = "Test fixture Op for validating gather and loop describe."

    g = list(describe(gather(A, B)))
    assert g[0] == (0, "gather")

    lp = list(describe(loop(body=A, until=lambda _: True, max_iterations=5)))
    assert lp[0][0] == 0
    assert "loop" in lp[0][1]
    assert "max_iterations=5" in lp[0][1]


def test_describe_handles_nested_compositions():
    class A(Op):
        Input = _M
        Output = _R
        Intent = "a"
        Meta = "Test fixture Op for validating nested compositions."

    class B(Op):
        Input = _R
        Output = _R
        Intent = "b"
        Meta = "Test fixture Op for validating nested compositions."

    class C(Op):
        Input = _R
        Output = _R
        Intent = "c"
        Meta = "Test fixture Op for validating nested compositions."

    tree = list(describe(sequence(A, branch_on(key=lambda _: "go", arms={"go": B}), C)))
    labels = [label for _, label in tree]
    assert "sequence" in labels
    assert "branch_on" in labels
    assert "A" in labels
    assert "B" in labels
    assert "C" in labels


# ---- show() handler -------------------------------------------------


def test_show_clean_library_prints_sections(capsys):
    exit_code = run(SimpleNamespace(library="examples.my_company"))
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Ops (" in out
    assert "HandleSupport" in out
    assert "[ENTRY]" in out
    # Composition's body is rendered.
    assert "sequence" in out
    assert "ClassifyIntent" in out
    assert "DraftResponse" in out
    # Snippets section appears.
    assert "Snippets (" in out
    # Tools section appears.
    assert "Tools (" in out


def test_show_entry_ops_sort_first(capsys):
    run(SimpleNamespace(library="examples.my_company"))
    out = capsys.readouterr().out
    # HandleSupport is the only entry-tagged Op; it should appear before
    # ClassifyIntent and DraftResponse in the Ops listing.
    hs_idx = out.index("HandleSupport")
    ci_idx = out.index("ClassifyIntent")
    assert hs_idx < ci_idx


def test_show_unimportable_library_errors(capsys):
    exit_code = run(SimpleNamespace(library="definitely.not.real.xyz"))
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "[FATAL]" in err


def test_show_empty_library_prints_hint(tmp_path, monkeypatch, capsys):
    """A library with no Ops surfaces a helpful hint, not a blank output."""
    import sys, textwrap

    pkg_dir = tmp_path / "temp_empty_lib"
    pkg_dir.mkdir()
    # __init__.py exists but doesn't import any ops module
    (pkg_dir / "__init__.py").write_text('"""empty"""\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    for key in [k for k in list(sys.modules) if k.startswith("temp_empty_lib")]:
        del sys.modules[key]

    exit_code = run(SimpleNamespace(library="temp_empty_lib"))
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "No Ops registered" in out


def test_show_smoke_branch_library_renders_branch_tree(capsys):
    """smoke_05_branch has branch_on — its body tree should include 'branch_on'."""
    pytest.importorskip("smoke_05_branch", reason="smoke library not installed")
    exit_code = run(SimpleNamespace(library="smoke_05_branch"))
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Route" in out
    assert "branch_on" in out
    assert "Triage" in out
    assert "HandleBilling" in out


def test_show_smoke_gather_library_renders_gather_tree(capsys):
    pytest.importorskip("smoke_07_gather", reason="smoke library not installed")
    exit_code = run(SimpleNamespace(library="smoke_07_gather"))
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "ResearchBrief" in out
    assert "gather" in out
    assert "EconomicAngle" in out
    assert "SocialAngle" in out
    assert "TechnicalAngle" in out


def test_show_smoke_loop_library_renders_loop_tree(capsys):
    pytest.importorskip("smoke_06_loop", reason="smoke library not installed")
    exit_code = run(SimpleNamespace(library="smoke_06_loop"))
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Brainstorm" in out
    assert "loop" in out
    assert "max_iterations=" in out
