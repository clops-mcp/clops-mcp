import pytest

from clops import Concept, Op, sequence
from clops.op import (
    SHORT_DESCRIPTION_MAX,
    OpMeta,
    short_description,
)
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
    assert "docs/migration-interpreter-swap.md" in str(exc.value)


def test_persistence_attribute_rejected():
    with pytest.raises(TypeError) as exc:
        class HasPersistence(Op):
            Input = Msg
            Output = Result
            Intent = "x"
            Meta = "Test fixture Op for validating the removed persistence attribute."
            persistence = "teammate"

    assert "`persistence`" in str(exc.value)
    assert "docs/migration-interpreter-swap.md" in str(exc.value)


def test_init_attribute_rejected():
    with pytest.raises(TypeError) as exc:
        class HasInit(Op):
            Input = Msg
            Output = Result
            Intent = "x"
            Meta = "Test fixture Op for validating the removed Init attribute."
            Init = Msg

    assert "`Init`" in str(exc.value)
    assert "docs/migration-interpreter-swap.md" in str(exc.value)


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


# ---- short_description -----------------------------------------------


def _op(intent: str, **extra) -> type:
    ns = {
        "Input": Msg,
        "Output": Result,
        "Intent": intent,
        "Meta": "Test fixture Op for validating short_description.",
        **extra,
    }
    return OpMeta("Fixture", (Op,), ns)


def test_short_description_takes_the_first_sentence():
    op = _op("Emit the greeting. Then wait for a reply before doing anything else.")
    assert short_description(op) == "Emit the greeting."


def test_short_description_stops_at_the_first_line():
    op = _op("Scope the diff.\nThen do a lot of other things on later lines.")
    assert short_description(op) == "Scope the diff."


def test_short_description_cuts_at_the_colon_introducing_detail():
    """A colon usually opens the enumeration the summary exists to drop."""
    op = _op(
        "Perform a thorough code review of the diff, decomposed into focused "
        "analysis steps: scope determination, context sampling, blindspot "
        "identification, and reporting."
    )
    assert short_description(op) == (
        "Perform a thorough code review of the diff, decomposed into focused "
        "analysis steps"
    )


def test_short_description_keeps_a_label_style_colon():
    """Cutting at every colon would reduce 'Goal: ...' to the word 'Goal'."""
    op = _op("Goal: review the diff and report what matters.")
    assert short_description(op) == "Goal: review the diff and report what matters."


def test_short_description_prefers_an_explicit_summary():
    op = _op("A long intent that says a great many things.", Summary="Reviews a diff.")
    assert short_description(op) == "Reviews a diff."


def test_short_description_collapses_whitespace_in_a_summary():
    op = _op("Whatever.", Summary="Reviews\n   a diff.")
    assert short_description(op) == "Reviews a diff."


def test_short_description_caps_a_long_summary():
    op = _op("Whatever.", Summary="x " * 200)
    assert len(short_description(op)) <= SHORT_DESCRIPTION_MAX + 1


def test_short_description_truncates_on_a_word_boundary():
    op = _op("alpha bravo charlie delta echo foxtrot golf hotel india juliett " * 5)
    out = short_description(op)
    assert out.endswith("…")
    assert len(out) <= SHORT_DESCRIPTION_MAX + 1
    assert "…" not in out[:-1]           # single trailing ellipsis
    assert out[:-1].rstrip().split()[-1] in {  # cut between words, not mid-word
        "alpha", "bravo", "charlie", "delta", "echo",
        "foxtrot", "golf", "hotel", "india", "juliett",
    }


def test_short_description_of_an_op_without_intent_is_empty():
    class Bare:
        pass

    assert short_description(Bare) == ""
