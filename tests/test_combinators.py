import pytest

from clops import Concept, Op, branch_on, gather, loop, sequence
from clops.combinators import BranchOn, Gather, Loop, Sequence, walk


class M(Concept):
    description = "m"


def _make(name):
    return type(
        name,
        (Op,),
        {"Input": M, "Output": M, "Intent": f"{name} intent", "Meta": "Test fixture."},
    )


def test_sequence_requires_at_least_one():
    with pytest.raises(ValueError):
        sequence()


def test_sequence_returns_frozen_structure():
    A = _make("A")
    B = _make("B")
    seq = sequence(A, B)
    assert isinstance(seq, Sequence)
    assert seq.steps == (A, B)


def test_branch_on_validates():
    A = _make("A")
    with pytest.raises(ValueError):
        branch_on(lambda x: x, {})
    with pytest.raises(TypeError):
        branch_on("not a callable", {"x": A})
    b = branch_on(lambda x: x, {"a": A})
    assert isinstance(b, BranchOn)


def test_gather_requires_two_branches():
    A = _make("A")
    with pytest.raises(ValueError):
        gather(A)
    B = _make("B")
    g = gather(A, B)
    assert isinstance(g, Gather)


def test_loop_validates():
    A = _make("A")
    with pytest.raises(TypeError):
        loop(A, until="not callable")
    lp = loop(A, until=lambda _: True)
    assert isinstance(lp, Loop)


def test_walk_finds_all_ops():
    A = _make("A")
    B = _make("B")
    C = _make("C")
    D = _make("D")
    tree = sequence(
        A,
        branch_on(lambda x: x, {"b": B, "c": C}),
        loop(D, until=lambda _: True),
    )
    found = list(walk(tree))
    assert set(found) == {A, B, C, D}
