import pytest

from clops import Concept, Op, sequence
from clops.registry import registry


class Msg(Concept):
    description = "A message."


class Result(Concept):
    description = "A result."


def test_missing_intent_rejected():
    with pytest.raises(TypeError):
        class NoIntent(Op):
            Input = Msg
            Output = Result


def test_missing_input_rejected():
    with pytest.raises(TypeError):
        class NoInput(Op):
            Output = Result
            Intent = "x"
            Meta = "Test fixture Op for validating missing Input."


def test_missing_output_rejected():
    with pytest.raises(TypeError):
        class NoOutput(Op):
            Input = Msg
            Intent = "x"
            Meta = "Test fixture Op for validating missing Output."


def test_input_must_be_concept():
    with pytest.raises(TypeError):
        class BadInput(Op):
            Input = str  # not a Concept
            Output = Result
            Intent = "x"
            Meta = "Test fixture Op for validating Input type check."


def test_team_attribute_rejected():
    with pytest.raises(TypeError) as exc:
        class HasTeam(Op):
            Input = Msg
            Output = Result
            Intent = "x"
            Meta = "Test fixture Op for validating the removed Team attribute."
            Team = {"helper": object}

    assert "`Team`" in str(exc.value)
    assert "teammate" in str(exc.value)
    assert "delete the attribute" in str(exc.value)


def test_persistence_attribute_rejected():
    with pytest.raises(TypeError) as exc:
        class HasPersistence(Op):
            Input = Msg
            Output = Result
            Intent = "x"
            Meta = "Test fixture Op for validating the removed persistence attribute."
            persistence = "teammate"

    assert "`persistence`" in str(exc.value)
    assert "delete the attribute" in str(exc.value)


def test_init_attribute_rejected():
    with pytest.raises(TypeError) as exc:
        class HasInit(Op):
            Input = Msg
            Output = Result
            Intent = "x"
            Meta = "Test fixture Op for validating the removed Init attribute."
            Init = Msg

    assert "`Init`" in str(exc.value)
    assert "delete the attribute" in str(exc.value)


def test_all_three_removed_attributes_reported_together():
    with pytest.raises(TypeError) as exc:
        class OldTeammate(Op):
            Input = Msg
            Output = Result
            Intent = "x"
            Meta = "Test fixture Op declaring the full removed teammate surface."
            persistence = "teammate"
            Init = Msg
            Team = {"helper": object}

    message = str(exc.value)
    for attr in ("`Team`", "`persistence`", "`Init`"):
        assert attr in message


def test_valid_leaf_op_registers():
    class MyOp(Op):
        Input = Msg
        Output = Result
        Intent = "Do the thing."
        Meta = "Test fixture Op for validating registration."

    assert registry.op("MyOp") is MyOp
    assert MyOp.is_leaf()


def test_composition_op_is_not_leaf():
    class A(Op):
        Input = Msg
        Output = Result
        Intent = "a"
        Meta = "Test fixture Op for validating composition."

    class B(Op):
        Input = Result
        Output = Result
        Intent = "b"
        Meta = "Test fixture Op for validating composition."

    class Parent(Op):
        Input = Msg
        Output = Result
        Intent = "chain"
        Meta = "Test fixture Op for validating composition detection."
        body = sequence(A, B)

    assert not Parent.is_leaf()
