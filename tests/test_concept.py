import pytest

from clops import Concept


def test_concept_requires_description():
    with pytest.raises(TypeError):
        class Broken(Concept):
            pass


def test_concept_sets_name_and_description():
    class Message(Concept):
        description = "A thing."

    assert Message.name == "Message"
    assert Message.description == "A thing."


def test_concept_subclasses_are_types():
    class A(Concept):
        description = "a"

    assert isinstance(A, type)
    assert issubclass(A, Concept)
