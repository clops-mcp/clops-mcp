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
    """`naming` is process-global; don't leak a name into other tests."""
    original = naming.server_name()
    yield
    naming.set_server_name(original)


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


# ---- the prefix itself -----------------------------------------------


def test_default_prefix():
    assert naming.tool("complete") == "mcp__clops__complete"


def test_prefix_follows_configured_name():
    naming.set_server_name("acme-dev")
    assert naming.tool("complete") == "mcp__acme-dev__complete"
    assert naming.tool("need") == "mcp__acme-dev__need"


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
    assert "mcp__acme-dev__complete" in reason
    assert "mcp__acme-dev__need" in reason
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

    assert "mcp__acme-dev__complete" in prompt
    assert "mcp__acme-dev__need" in prompt
    assert "mcp__clops__" not in prompt


# ---- generated project config ----------------------------------------


def test_build_mcp_json_uses_custom_name_consistently():
    """The .mcp.json key and the server's own --server-name must agree, or the
    server would advertise a prefix the client never uses."""
    from clops.cli.init import build_mcp_json

    mcp = build_mcp_json(["my_ops"], [], "acme-dev")

    assert list(mcp["mcpServers"]) == ["acme-dev"]
    args = mcp["mcpServers"]["acme-dev"]["args"]
    assert "--server-name" in args
    assert args[args.index("--server-name") + 1] == "acme-dev"


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
    """`clops-server --server-name` must actually take effect on the process."""
    from clops.runtime.mcp_server import build_server_from_argv

    build_server_from_argv(["--library", "examples.my_company", "--server-name", "acme-dev"])
    assert naming.server_name() == "acme-dev"
    assert naming.tool("complete") == "mcp__acme-dev__complete"
