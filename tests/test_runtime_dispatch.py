from clops import Concept, Op, Snippet, SnippetRole, Tool
from clops.runtime.dispatch import build_agent_config, render_prompt


class Msg(Concept):
    description = "A thing."


class Out(Concept):
    description = "A result."


def _make_op():
    safety = Snippet(id="safety", content="do no harm")
    Snippet(id="bv", role="brand_voice", content="warm")
    tool = Tool(name="lookup", description="lookup data")

    class DoThing(Op):
        Input = Msg
        Output = Out
        Intent = "Do the thing carefully."
        Meta = "Test fixture Op for validating prompt rendering."
        Uses = [safety]
        Requires = [SnippetRole("brand_voice")]
        Tools = [tool]

    return DoThing


def test_prompt_includes_intent_and_policies():
    Op = _make_op()
    prompt = render_prompt(Op, {"content": "hi"}, execution_id="exec_x")
    assert "Do the thing carefully." in prompt
    assert "do no harm" in prompt
    assert "warm" in prompt


def test_prompt_includes_concept_descriptions():
    Op = _make_op()
    prompt = render_prompt(Op, {"content": "hi"}, execution_id="exec_x")
    assert "Msg:" in prompt
    assert "Out:" in prompt
    assert "A thing." in prompt
    assert "A result." in prompt


def test_prompt_embeds_execution_id_in_exit_conditions():
    Op = _make_op()
    prompt = render_prompt(Op, "hello", execution_id="exec_abcdef")
    assert "exec_abcdef" in prompt
    # Both complete and need should reference the id explicitly
    assert 'mcp__clops__complete(execution_id="exec_abcdef"' in prompt
    assert 'mcp__clops__need(execution_id="exec_abcdef"' in prompt


def test_prompt_mentions_op_tools_via_call_tool():
    Op = _make_op()
    prompt = render_prompt(Op, "hi", execution_id="exec_x")
    # Tools are dispatched through the single call_tool entry point.
    assert "mcp__clops__call_tool" in prompt
    # The tool is named in the prompt so the subagent knows what to pass.
    assert "`lookup`" in prompt
    assert "lookup data" in prompt
    # No per-tool MCP entry should be advertised.
    assert "mcp__clops__lookup" not in prompt


def test_agent_config_shape_is_minimal():
    Op = _make_op()
    config = build_agent_config(Op, "x", run_id="r1", execution_id="e1")
    # Per spec: only description, prompt, optional model. No tools/maxTurns/hooks.
    public_keys = {k for k in config if not k.startswith("_")}
    assert public_keys == {"description", "prompt"}
    assert config["description"] == "Execute DoThing for r1"
    assert config["_metadata"] == {
        "run_id": "r1",
        "execution_id": "e1",
        "op_name": "DoThing",
    }


def test_agent_config_adds_model_when_op_declares_one():
    class WithModel(Op):
        Input = Msg
        Output = Out
        Intent = "explicit model"
        Meta = "Test fixture Op for validating model config."
        Model = "sonnet"

    config = build_agent_config(WithModel, "x", run_id="r1", execution_id="e1")
    assert config["model"] == "sonnet"


# ---- Manifest output contract ----------------------------------------


def test_default_contract_asks_for_full_output():
    Op = _make_op()
    prompt = render_prompt(Op, "hi", execution_id="exec_x")
    assert "## What you'll produce" in prompt
    assert "## What to hold by the end" not in prompt
    assert "one-line manifest" not in prompt


def test_manifest_mode_lightens_a_non_inband_leaf():
    Op = _make_op()
    prompt = render_prompt(
        Op, "hi", execution_id="exec_x",
        manifest_mode=True, require_full_output=False,
    )
    # Hold-checklist framing replaces the serialize-everything framing.
    assert "## What to hold by the end" in prompt
    assert "## What you'll produce" not in prompt
    # complete() asks for a one-line manifest, not the full contents.
    assert "one-line manifest" in prompt
    # The Output concept is still named so the agent knows what to hold.
    assert "Out" in prompt


def test_manifest_mode_keeps_inband_leaf_full():
    # A leaf whose output is consumed in-band (branch/loop/terminal) keeps the
    # full-output contract even when the run is in manifest mode.
    Op = _make_op()
    prompt = render_prompt(
        Op, "hi", execution_id="exec_x",
        manifest_mode=True, require_full_output=True,
    )
    assert "## What you'll produce" in prompt
    assert "## What to hold by the end" not in prompt
    assert "one-line manifest" not in prompt
