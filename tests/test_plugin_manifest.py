"""The plugin has to be a complete install on its own.

There are two documented ways to get clops, and they have to actually be two:

    1. `uvx` + a project `.mcp.json` — works in any MCP client
    2. `claude plugin install` — Claude Code only, one command

Path 2 was previously *not* an install. The plugin shipped a skill and an agent
and nothing else, so a reader who followed the marketplace instructions got no
MCP server and no hook, and nothing said so. These tests pin the four pieces
that make it a real path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

MANIFEST = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"


@pytest.fixture(scope="module")
def plugin() -> dict:
    if not MANIFEST.exists():  # pragma: no cover - sdist prunes .claude-plugin
        pytest.skip(".claude-plugin not present (sdist)")
    return json.loads(MANIFEST.read_text())


def test_the_plugin_registers_the_mcp_server(plugin):
    """Without this the marketplace path installs a skill that describes a
    relay loop against a server the user does not have."""
    server = plugin["mcpServers"]["clops"]
    assert server["command"] == "uvx"
    assert server["args"] == ["clops-mcp"]


def test_the_plugin_server_passes_no_library(plugin):
    """A globally-installed server cannot know the project's libraries, and
    must not guess. With no `--library`, `build_server_from_argv` falls back to
    reading `.clops` from the project directory — so one global server serves
    whatever each project declares."""
    assert "--library" not in plugin["mcpServers"]["clops"]["args"]


def test_the_plugin_registers_the_subagent_stop_hook(plugin):
    """clops needs the MCP server, subagents, and the SubagentStop hook working
    together. The hook fails open, so a missing one degrades quietly rather
    than erroring — which is exactly why its absence needs a test."""
    entry = plugin["hooks"]["SubagentStop"][0]
    assert entry["matcher"] == ""
    assert "clops-hook" in entry["hooks"][0]["command"]


def test_the_plugin_still_ships_the_skill_and_agent(plugin):
    assert plugin["skills"]
    assert any("clops-executor" in a for a in plugin["agents"])


@pytest.mark.parametrize("declared", ["skills", "agents", "mcpServers", "hooks"])
def test_declared_paths_exist(plugin, declared):
    """A path typo in the manifest is a runtime load failure at the user's end,
    not ours. Only the file-backed keys are checked; the others are commands."""
    if declared in ("mcpServers", "hooks"):
        pytest.skip("commands, not paths")
    root = MANIFEST.parent.parent
    entries = plugin[declared]
    for rel in [entries] if isinstance(entries, str) else entries:
        assert (root / rel.lstrip("./")).exists(), f"{declared}: {rel} does not exist"
