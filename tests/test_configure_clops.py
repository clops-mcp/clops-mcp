"""A clops with no libraries has to say so, and say what to do about it.

`list_processes` on a fresh install returns an empty list. Nothing indicates
that something is missing, which library format is accepted, or where the
library list even lives — and that is most people's first contact with clops.

`configure_clops` answers that. It returns instructions rather than starting a
run, because setup is a couple of file edits and a restart; walking that
through the dispatch loop one Op at a time would be slower and more fragile
than just saying it.
"""

from __future__ import annotations

import json

import pytest

from clops.runtime.mcp_server import (
    MAIN_TOOL_NAMES,
    FlowServer,
    ServerConfig,
    bundled_libraries,
    configure_guidance,
)


def guidance(**kw):
    base = dict(
        libraries=[], import_error=None, project_dir="/proj", libraries_from_argv=False
    )
    return configure_guidance(**{**base, **kw})


# ---- state detection -------------------------------------------------


def test_no_libraries_is_reported_as_a_state_not_an_empty_success():
    out = guidance()
    assert out["state"] == "no_libraries"
    assert "no Op libraries" in out["next_step"]


def test_a_broken_library_reports_the_error_rather_than_looking_unconfigured():
    out = guidance(libraries=["my_ops"], import_error="No module named 'my_ops'")
    assert out["state"] == "import_failed"
    assert "my_ops" in out["next_step"]


def test_a_working_setup_says_so_briefly_and_stops():
    """Nobody needs setup instructions when setup is done; the long-form advice
    would just be noise in the context."""
    out = guidance(libraries=["my_ops"])
    assert out["state"] == "ready"
    assert "list_processes" in out["next_step"]
    assert "TO ADD ONE" not in out["next_step"]


# ---- the two install shapes need different advice --------------------


def test_shared_mode_points_at_dot_clops():
    out = guidance()
    assert out["mode"] == "shared"
    assert "/proj/.clops" in out["next_step"]


def test_shared_mode_admits_it_cannot_install_anything():
    """The trap this exists to prevent. The plugin's server runs under
    `uvx clops-mcp` with nothing else in the environment, so pointing `.clops`
    at a local path or a git URL fails with ModuleNotFoundError and no
    explanation. Verified against the real server before writing this."""
    text = guidance()["next_step"]
    assert "can only load libraries already importable" in text
    assert "clops init" in text  # the way out: a per-project server


def test_project_mode_warns_that_library_flags_beat_dot_clops():
    """`build_server_from_argv` does `ns.library if ns.library else
    clops_config.libraries` — the flags win outright. Someone who edits
    `.clops` in a project set up by `clops init` changes nothing at all, and
    nothing tells them."""
    out = guidance(libraries_from_argv=True)
    assert out["mode"] == "project"
    assert "override `.clops`" in out["next_step"]


def test_ready_state_skips_the_mode_specific_warnings():
    for from_argv in (True, False):
        text = guidance(libraries=["x"], libraries_from_argv=from_argv)["next_step"]
        assert "WATCH OUT" not in text
        assert "SHARED-SERVER LIMIT" not in text


# ---- the offer of something that actually runs -----------------------


def test_bundled_libraries_are_offered_when_there_are_none():
    """A user with no library of their own still needs a way to see clops work.
    These ship in the wheel, so they import in any environment."""
    out = guidance()
    assert out["bundled_libraries"]
    assert all(b.startswith("clops.example_library.") for b in out["bundled_libraries"])
    assert out["bundled_libraries"][0] in out["next_step"]


def test_bundled_libraries_resolves_against_the_real_package():
    assert "clops.example_library.session_analyzer" in bundled_libraries()


def test_the_caller_is_told_not_to_invent_a_library():
    assert "Do not guess or invent one" in guidance()["next_step"]


# ---- wiring ----------------------------------------------------------


def test_it_still_answers_when_a_library_failed_to_import():
    """`_dispatch_tool_call` short-circuits MAIN_TOOL_NAMES on an import error.
    A broken library is exactly when someone needs this tool, so it must not be
    in that list — otherwise it refuses to answer with the error it exists to
    explain."""
    assert "configure_clops" not in MAIN_TOOL_NAMES

    srv = FlowServer(ServerConfig(libraries=["definitely_not_a_module"]))
    srv.load_library_safe()
    payload = json.loads(srv._dispatch_tool_call("configure_clops", {})[0].text)
    assert payload["state"] == "import_failed"


def test_the_tool_is_advertised():
    srv = FlowServer(ServerConfig(libraries=[]))
    tool = next(t for t in srv._build_tool_catalog() if t.name == "configure_clops")
    assert "list_processes is empty" in tool.description
    assert tool.inputSchema["properties"] == {}


def test_the_server_records_which_mode_it_booted_in():
    """Nothing else distinguishes them after boot, and the advice differs."""
    from clops.runtime.mcp_server import build_server_from_argv

    assert build_server_from_argv(["--library", "x"]).config.libraries_from_argv
    assert not build_server_from_argv([]).config.libraries_from_argv
