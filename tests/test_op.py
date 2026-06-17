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
