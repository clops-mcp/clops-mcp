"""Tests for the configurable MCP server name.

The name decides the tool prefix (`mcp__<server>__<tool>`) that Claude Code uses
to namespace our tools. Getting it wrong doesn't fail loudly — it produces
prompts telling subagents to call tools that don't exist — so the coverage here
is mostly "does the name reach every place that names a tool".
"""

from __future__ import annotations

import pytest

from clops import naming


@pytest.fixture(autouse=True)
def restore_server_name():
    """`naming` is process-global; don't leak a name or pattern into other tests."""
    original = naming.server_name()
    original_pattern = naming.tool_pattern()
    yield
    naming.set_server_name(original)
    naming.set_tool_pattern(original_pattern)


# ---- validation ------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["clops", "acme-dev", "clops_support", "a", "agent2"],
)
def test_valid_names_accepted(name):
    assert naming.validate_server_name(name) == name


@pytest.mark.parametrize(
    "name, why",
    [
        ("", "empty"),
        ("   ", "whitespace only"),
        ("has space", "spaces break the tool identifier"),
        ("-leading", "must start alphanumeric"),
        ("a__b", "'__' is the mcp__x__y delimiter"),
        ("emoji✨", "non-ascii"),
    ],
)
def test_invalid_names_rejected(name, why):
    with pytest.raises(ValueError):
        naming.validate_server_name(name)


def test_name_is_stripped():
    assert naming.validate_server_name("  clops  ") == "clops"


# ---- auto-qualification ----------------------------------------------
#
# Every clops-derived server keeps `clops` in its name, so a person reading a
# tool list (or a grep) can tell they all speak the same protocol.


@pytest.mark.parametrize(
    "given, expected",
    [
        ("acme-dev", "clops-acme-dev"),   # the hint gets added
        ("support", "clops-support"),
        ("clops", "clops"),                        # already says it
        ("clops-support", "clops-support"),        # no double prefix
        ("my-clops-thing", "my-clops-thing"),      # says it anywhere, leave alone
        ("CLOPS-Prod", "CLOPS-Prod"),              # case-insensitive check
    ],
)
def test_qualify_adds_the_hint_without_doubling(given, expected):
    assert naming.qualify_server_name(given) == expected


def test_qualify_is_idempotent():
    """init qualifies, then the server it launches qualifies again — must not drift."""
    once = naming.qualify_server_name("acme-dev")
    assert naming.qualify_server_name(once) == once


def test_set_server_name_qualifies():
    naming.set_server_name("acme-dev")
    assert naming.server_name() == "clops-acme-dev"


# ---- the prefix itself -----------------------------------------------


def test_default_prefix():
    assert naming.tool("complete") == "mcp__clops__complete"


def test_prefix_follows_configured_name():
    naming.set_server_name("acme-dev")
    assert naming.tool("complete") == "mcp__clops-acme-dev__complete"
    assert naming.tool("need") == "mcp__clops-acme-dev__need"


def test_set_server_name_rejects_invalid():
    with pytest.raises(ValueError):
        naming.set_server_name("no spaces allowed")


# ---- the places that name tools --------------------------------------


def test_hook_block_reason_follows_server_name():
    """The hook tells a stalled subagent what to call. Wrong prefix = dead end."""
    from clops.runtime.hook_server import block_reason

    assert "mcp__clops__complete" in block_reason()

    naming.set_server_name("acme-dev")
    reason = block_reason()
    assert "mcp__clops-acme-dev__complete" in reason
    assert "mcp__clops-acme-dev__need" in reason
    # The bare default must be gone, or a renamed server still names the
    # wrong tool. (`mcp__clops-acme-dev__` does not contain `mcp__clops__`.)
    assert "mcp__clops__" not in reason


def test_dispatch_prompt_follows_server_name():
    """The dispatch prompt is the authoritative instruction to each subagent."""
    from clops.concept import Concept
    from clops.field import Field
    from clops.op import Op
    from clops.runtime.dispatch import render_prompt

    class Brief(Concept):
        description = "A brief"
        goal = Field("What to do")

    class Summary(Concept):
        description = "A summary"
        text = Field("The summary")

    class DoWork(Op):
        Input = Brief
        Output = Summary
        Intent = "Do the work"
        Meta = "Fixture Op; exists only to render a dispatch prompt."

    naming.set_server_name("acme-dev")
    prompt = render_prompt(DoWork, {"goal": "x"}, execution_id="exec_123")

    assert "mcp__clops-acme-dev__complete" in prompt
    assert "mcp__clops-acme-dev__need" in prompt
    assert "mcp__clops__" not in prompt


# ---- generated project config ----------------------------------------


def test_build_mcp_json_uses_custom_name_consistently():
    """The .mcp.json key and the server's own --server-name must agree, or the
    server would advertise a prefix the client never uses."""
    from clops.cli.init import build_mcp_json

    mcp = build_mcp_json(["my_ops"], [], "acme-dev")

    assert list(mcp["mcpServers"]) == ["clops-acme-dev"]
    args = mcp["mcpServers"]["clops-acme-dev"]["args"]
    assert "--server-name" in args
    # The qualified form is what's passed through, so the server doesn't have to
    # re-derive it and can't disagree with the key above.
    assert args[args.index("--server-name") + 1] == "clops-acme-dev"


def test_build_mcp_json_default_omits_the_flag():
    """Default stays byte-identical to before this feature — no stray flags."""
    from clops.cli.init import build_mcp_json

    mcp = build_mcp_json(["my_ops"], [])

    assert list(mcp["mcpServers"]) == ["clops"]
    assert "--server-name" not in mcp["mcpServers"]["clops"]["args"]


def test_build_mcp_json_rejects_invalid_name():
    from clops.cli.init import build_mcp_json

    with pytest.raises(ValueError):
        build_mcp_json(["my_ops"], [], "not a valid name")


def test_server_argv_sets_the_name():
    """`clops-mcp --server-name` must actually take effect on the process."""
    from clops.runtime.mcp_server import build_server_from_argv

    build_server_from_argv(["--library", "examples.my_company", "--server-name", "acme-dev"])
    assert naming.server_name() == "clops-acme-dev"
    assert naming.tool("complete") == "mcp__clops-acme-dev__complete"


# ---- tool pattern ----------------------------------------------------
#
# `mcp__<server>__<tool>` is a Claude Code convention, not part of MCP. Behind a
# gateway the client sees something else — IBM ContextForge re-exposes
# `complete` as `clops-support-complete` — and a dispatch prompt naming the
# wrong one tells the subagent to call a tool that isn't on its list, which
# stalls the run at its first step. Verified against a real gateway; see
# deploy/context-forge/README.md.


def test_default_pattern_is_the_claude_code_form():
    assert naming.tool("complete") == "mcp__clops__complete"


def test_pattern_can_match_a_gateway_that_renames_tools():
    naming.set_tool_pattern("clops-support-{name_hyphenated}")
    assert naming.tool("list_processes") == "clops-support-list-processes"
    assert naming.tool("complete") == "clops-support-complete"


def test_hyphenated_placeholders_leave_already_hyphenated_text_alone():
    naming.set_server_name("acme-dev")
    naming.set_tool_pattern("{server_hyphenated}-{name_hyphenated}")
    assert naming.tool("step_complete") == "clops-acme-dev-step-complete"


def test_pattern_and_server_name_compose():
    naming.set_server_name("support")
    naming.set_tool_pattern("{server}::{name}")
    assert naming.tool("need") == "clops-support::need"


def test_bare_name_pattern_is_allowed():
    """The lowest-common-denominator option: name the tool and let the client
    resolve it. Valid because {name} is present."""
    naming.set_tool_pattern("{name}")
    assert naming.tool("complete") == "complete"


@pytest.mark.parametrize(
    "pattern",
    [
        "",
        "   ",
        "mcp__{server}__complete",  # no {name}: every tool renders the same
        "{server}",
    ],
)
def test_pattern_without_a_name_placeholder_is_rejected(pattern):
    with pytest.raises(ValueError):
        naming.set_tool_pattern(pattern)


def test_unknown_placeholder_is_rejected_rather_than_exploding_later():
    """A typo must fail at startup. Left to render time it is a KeyError from
    inside prompt generation, which is a much worse place to find out."""
    with pytest.raises(ValueError, match="unknown placeholder"):
        naming.set_tool_pattern("mcp__{server}__{tool}")


def test_rejected_pattern_does_not_take_effect():
    naming.set_tool_pattern("{name}")
    with pytest.raises(ValueError):
        naming.set_tool_pattern("{nope}")
    assert naming.tool_pattern() == "{name}"


def test_pattern_reaches_the_hook_block_message():
    """The block reason is the other place a tool gets named, and it is the one
    that fires exactly when a run is already going wrong."""
    from clops.runtime.hook_server import block_reason

    naming.set_tool_pattern("clops-support-{name_hyphenated}")
    reason = block_reason()
    assert "clops-support-complete" in reason
    assert "clops-support-need" in reason
    assert "mcp__" not in reason


def test_pattern_reaches_dispatch_prompts():
    """The failure that started this: start_process returns a prompt naming the
    tools the subagent must call back with."""
    from clops import Concept, Op
    from clops.runtime import Runtime

    class Msg(Concept):
        description = "a message"

    class Res(Concept):
        description = "a result"

    class Probe(Op):
        Input = Msg
        Output = Res
        Intent = "probe tool naming"
        Meta = "Test fixture Op for checking tool names inside dispatch prompts."
        entry = True

    naming.set_tool_pattern("clops-support-{name_hyphenated}")
    prompt = Runtime().start("Probe", "hi", enforce_entry=True)["agent_config"]["prompt"]

    assert "clops-support-complete" in prompt
    assert "mcp__clops__complete" not in prompt


def test_server_argv_sets_the_pattern():
    from clops.runtime.mcp_server import build_server_from_argv

    build_server_from_argv(
        ["--library", "examples.my_company", "--tool-pattern", "gw-{name_hyphenated}"]
    )
    assert naming.tool("step_complete") == "gw-step-complete"


def test_server_argv_rejects_a_bad_pattern(capsys):
    """argparse.error exits 2 rather than raising a traceback at the operator."""
    from clops.runtime.mcp_server import build_server_from_argv

    with pytest.raises(SystemExit):
        build_server_from_argv(
            ["--library", "examples.my_company", "--tool-pattern", "{bogus}"]
        )
    assert "unknown placeholder" in capsys.readouterr().err
