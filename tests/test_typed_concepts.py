"""Tests for typed Concept fields (Phase 1)."""

from __future__ import annotations

from clops import Concept, Field


# ---- Field basics ----------------------------------------------------


def test_field_description():
    f = Field("The task name")
    assert f.description == "The task name"
    assert f.required is True


def test_field_optional():
    f = Field("Notes", required=False)
    assert f.required is False


def test_field_repr():
    f = Field("The task name")
    f.name = "task_name"
    assert "task_name" in repr(f)
    assert "required" in repr(f)


# ---- ConceptMeta collection -----------------------------------------


def test_concept_collects_fields():
    class Task(Concept):
        description = "A work item"
        name = Field("The task name")
        status = Field("pending or done")

    assert len(Task._fields) == 2
    assert "name" in Task._fields
    assert "status" in Task._fields


def test_concept_field_names_set_by_metaclass():
    class Item(Concept):
        description = "An item"
        title = Field("The title")
        count = Field("How many", required=False)

    assert Item._fields["title"].name == "title"
    assert Item._fields["count"].name == "count"


def test_concept_without_fields_has_empty_dict():
    class Plain(Concept):
        description = "No fields"

    assert hasattr(Plain, "_fields")
    assert len(Plain._fields) == 0


def test_concept_field_required_default():
    class Doc(Concept):
        description = "A document"
        content = Field("The content")
        author = Field("Who wrote it", required=False)

    assert Doc._fields["content"].required is True
    assert Doc._fields["author"].required is False


def test_concept_description_not_collected_as_field():
    """'description' is a reserved Concept attribute, not a Field."""
    class Thing(Concept):
        description = "A thing"
        name = Field("The name")

    assert "description" not in Thing._fields
    assert "name" in Thing._fields


# ---- Rendering helpers -----------------------------------------------


def test_render_fields_for_prompt():
    """Fields render as a list of name (required/optional): description."""
    class Task(Concept):
        description = "A work item"
        name = Field("The task name")
        status = Field("pending or done")
        notes = Field("Additional notes", required=False)

    fields = Task._fields
    lines = []
    for f in fields.values():
        req = "required" if f.required else "optional"
        lines.append(f"  - {f.name} ({req}): {f.description}")

    rendered = "\n".join(lines)
    assert "name (required): The task name" in rendered
    assert "status (required): pending or done" in rendered
    assert "notes (optional): Additional notes" in rendered


# ---- Dispatch prompt integration ------------------------------------


def test_dispatch_prompt_includes_input_fields():
    """Fields appear in the dispatch prompt under 'What you'll receive'."""
    from clops import Op
    from clops.registry import registry
    from clops.runtime.dispatch import render_prompt

    registry.clear()

    class TaskInput(Concept):
        description = "A task to execute"
        name = Field("The task name")
        priority = Field("High, medium, or low", required=False)

    class TaskOutput(Concept):
        description = "Result of the task"
        summary = Field("What was done")

    class DoTask(Op):
        Input = TaskInput
        Output = TaskOutput
        Intent = "Execute the task"
        Meta = "Test."
        entry = True

    prompt = render_prompt(DoTask, "test input", execution_id="exec-1")
    assert "name (required): The task name" in prompt
    assert "priority (optional): High, medium, or low" in prompt
    assert "summary (required): What was done" in prompt

    registry.clear()


def test_dispatch_prompt_no_fields_still_works():
    """Concepts without Fields render normally (no crash, no empty section)."""
    from clops import Op
    from clops.registry import registry
    from clops.runtime.dispatch import render_prompt

    registry.clear()

    class PlainIn(Concept):
        description = "Plain input"

    class PlainOut(Concept):
        description = "Plain output"

    class PlainOp(Op):
        Input = PlainIn
        Output = PlainOut
        Intent = "Do plain work"
        Meta = "Test."
        entry = True

    prompt = render_prompt(PlainOp, "test", execution_id="exec-1")
    assert "PlainIn: Plain input" in prompt
    assert "PlainOut: Plain output" in prompt

    registry.clear()


def test_state_store_prompt_shows_value_type_fields():
    """Dict store with typed value shows field hints."""
    from clops.runtime.state_manager import StateManager

    class Item(Concept):
        description = "An item"
        title = Field("The title")
        done = Field("Whether it's done", required=False)

    sm = StateManager("run-test")
    sm.register_store("items", "dict", value_type=Item)
    rendered = sm.render_for_prompt()
    assert "title (required)" in rendered
    assert "done (optional)" in rendered


# ---- bulk fields -----------------------------------------------------


def test_field_bulk_defaults_false():
    assert Field("The task name").bulk is False


def test_field_bulk_opt_in():
    f = Field("the full flow records", bulk=True)
    assert f.bulk is True
    assert f.required is True


def test_field_repr_shows_bulk():
    f = Field("the records", bulk=True)
    f.name = "flows"
    assert "bulk" in repr(f)
    assert "bulk" not in repr(Field("the count"))


def test_bulk_field_renders_qualifier_and_relay_note():
    """A bulk Output field is labelled and carries the relay instruction."""
    from clops.runtime.dispatch import _render_concept_fields

    class FlowManifest(Concept):
        description = "A manifest of the characterised flows."
        handle = Field("the handle holding the records")
        flows = Field("the full flow records", bulk=True)

    rendered = "\n".join(_render_concept_fields(FlowManifest, relay_note=True))
    assert "flows (required, bulk): the full flow records" in rendered
    assert "handle (required): the handle holding the records" in rendered
    assert "unbounded collection" in rendered
    assert "reference plus a count" in rendered


def test_relay_note_omitted_without_bulk_fields():
    from clops.runtime.dispatch import _render_concept_fields

    class Plain(Concept):
        description = "A plain output."
        summary = Field("What was done")

    rendered = "\n".join(_render_concept_fields(Plain, relay_note=True))
    assert "unbounded collection" not in rendered
    assert "summary (required): What was done" in rendered


def test_relay_note_not_rendered_on_the_input_side():
    """The note is about what you hand back, so it's Output-only."""
    from clops.runtime.dispatch import _render_concept_fields

    class Bulky(Concept):
        description = "Bulky input."
        records = Field("the records", bulk=True)

    rendered = "\n".join(_render_concept_fields(Bulky))
    assert "records (required, bulk): the records" in rendered
    assert "unbounded collection" not in rendered


def test_dispatch_prompt_carries_relay_note_for_bulk_output():
    from clops import Op
    from clops.registry import registry
    from clops.runtime.dispatch import render_prompt

    registry.clear()

    class Brief(Concept):
        description = "A brief."
        goal = Field("What to do")

    class Findings(Concept):
        description = "A manifest of findings."
        handle = Field("the handle holding the findings")
        findings = Field("the full finding records", bulk=True)

    class Audit(Op):
        Input = Brief
        Output = Findings
        Intent = "Audit the thing."
        Meta = "Test."
        entry = True

    prompt = render_prompt(Audit, {"goal": "go"}, execution_id="e1")
    assert "findings (required, bulk): the full finding records" in prompt
    assert "unbounded collection" in prompt
    # The input side stays clean.
    assert "goal (required): What to do" in prompt
