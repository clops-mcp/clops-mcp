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
    assert "clops-mcp" in server["args"]


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


# ---- manifest / package skew -----------------------------------------


def _server_args(plugin) -> list[str]:
    """The part of the uvx command line that clops-mcp itself receives.

    Everything before the `clops-mcp` element is uvx's (`--from`, `--with`);
    everything after is the server's.
    """
    args = plugin["mcpServers"]["clops"]["args"]
    return args[args.index("clops-mcp") + 1 :]


def test_every_flag_the_manifest_passes_is_one_the_server_knows(plugin):
    """The manifest and the package ship through different channels — the
    manifest from this repo's default branch, the package from PyPI — so they
    can disagree about what flags exist.

    That disagreement cost a broken install: plugin 0.4.4 passed
    `--default-library`, which did not land in the package until 0.4.5, and the
    server argparse-exited before the MCP handshake. Claude Code reported
    `-32000: Connection closed`, which says nothing about the cause.

    This catches the direction CI can see: a manifest naming a flag this
    codebase does not have.
    """
    from clops.runtime.mcp_server import build_server_from_argv

    flags = [a for a in _server_args(plugin) if a.startswith("--")]
    assert flags, "manifest passes no server flags — did the args shape change?"

    # Round-trip the real command line. `build_server_from_argv` now tolerates
    # unknown flags, so assert on what it *reports* rather than on it exiting.
    import io
    import contextlib

    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        build_server_from_argv(_server_args(plugin))
    assert "unrecognised arguments" not in err.getvalue(), (
        "the manifest passes a flag this build does not implement: " + err.getvalue()
    )


def test_the_manifest_pins_a_version_floor(plugin):
    """Bare `uvx clops-mcp` always takes latest, which is what opened the
    window: the manifest shipped a flag before the release implementing it.

    The floor must be the version that introduced the newest flag the manifest
    uses — not the current version, because `main` is ahead of PyPI between
    merging a release PR and publishing it. A floor equal to the repo version
    would demand something unpublished.
    """
    args = plugin["mcpServers"]["clops"]["args"]
    assert args[0] == "--from", "no version floor — `uvx clops-mcp` takes latest"
    spec = args[1]
    assert spec.startswith("clops-mcp>="), f"expected a floor, got {spec!r}"


def test_the_floor_is_a_version_that_actually_exists_here(plugin):
    """A floor above this codebase's own version can never be satisfied by a
    release cut from it."""
    import tomllib
    from pathlib import Path

    from packaging.version import Version

    args = plugin["mcpServers"]["clops"]["args"]
    floor = Version(args[1].split(">=", 1)[1])
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    current = Version(tomllib.loads(pyproject.read_text())["project"]["version"])
    assert floor <= current, f"floor {floor} exceeds this repo's version {current}"
