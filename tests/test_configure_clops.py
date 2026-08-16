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


# ---- the bundled fallback --------------------------------------------


def test_the_fallback_is_declared_as_a_demo_not_as_the_project(monkeypatch, tmp_path):
    """A fresh plugin install used to show an empty `list_processes`. It now
    shows something, and the risk flips: someone could reasonably conclude that
    clops *is* a session analyser. The copy has to head that off."""
    out = guidance(
        libraries=["clops.example_library.session_analyzer"], using_default_library=True
    )
    assert out["state"] == "default_only"
    assert "demo" in out["next_step"]
    assert "not what clops is for" in out["next_step"]
    # and it still explains how to replace it
    assert "TO ADD ONE" in out["next_step"]


def test_a_real_library_is_not_labelled_a_demo():
    out = guidance(libraries=["my_ops"])
    assert out["state"] == "ready"
    assert "demo" not in out["next_step"]


# ---- resolution order ------------------------------------------------


def test_the_default_only_applies_when_nothing_else_resolves(tmp_path, monkeypatch):
    """Fallback, not addition. A project that declares its own libraries must
    not also get the demo cluttering its process list."""
    from clops.runtime.mcp_server import build_server_from_argv

    monkeypatch.chdir(tmp_path)
    default = ["--default-library", "clops.example_library.session_analyzer"]

    empty = build_server_from_argv(default)
    assert empty.config.libraries == ["clops.example_library.session_analyzer"]
    assert empty.config.using_default_library

    explicit = build_server_from_argv(["--library", "clops.example_library.core"] + default)
    assert explicit.config.libraries == ["clops.example_library.core"]
    assert not explicit.config.using_default_library

    (tmp_path / ".clops").write_text("clops.example_library.code_review\n")
    from_file = build_server_from_argv(default)
    assert from_file.config.libraries == ["clops.example_library.code_review"]
    assert not from_file.config.using_default_library


def test_the_fallback_actually_produces_a_runnable_process(tmp_path):
    """The whole point: an empty `list_processes` is the thing being fixed, so
    assert on the runtime rather than on the config.

    Run in a subprocess because Ops register as a side effect of module import,
    and `sys.modules` caches. The autouse registry-clearing fixture cannot undo
    that, so a sibling test that already imported this library would leave this
    one looking at an empty registry and passing or failing for the wrong
    reason. A clean interpreter is the only honest way to ask the question.
    """
    import subprocess
    import sys

    code = (
        "from clops.runtime.mcp_server import build_server_from_argv as b;"
        "s=b(['--default-library','clops.example_library.session_analyzer']);"
        "print([p['name'] for p in s.runtime.list_processes()])"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert "AnalyzeSession" in out.stdout


def test_the_plugin_ships_a_default_library(tmp_path):
    """Without this the plugin installs a server with nothing to run, which is
    what made the marketplace path feel broken even once it worked."""
    import json as _json
    from pathlib import Path as _Path

    manifest = _Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    if not manifest.exists():  # pragma: no cover - sdist prunes it
        pytest.skip(".claude-plugin not present")
    args = _json.loads(manifest.read_text())["mcpServers"]["clops"]["args"]
    assert "--default-library" in args
    # A fallback, never a hard --library: that would suppress every project's
    # own configuration.
    assert "--library" not in args
    assert any(a.startswith("clops.example_library.") for a in args)


# ---- surviving a launcher newer than this build ----------------------


def test_an_unknown_flag_does_not_kill_the_server(capsys):
    """The plugin manifest ships from the repo's default branch and the package
    from PyPI, so a manifest can name a flag whose release has not landed.

    That happened: plugin 0.4.4 passed `--default-library`, which arrived in
    0.4.5. argparse exited before the MCP handshake and the client reported
    `-32000: Connection closed` — a symptom three levels away from the cause.

    Degrading costs one feature. Exiting costs the whole server, in the least
    debuggable way available.
    """
    from clops.runtime.mcp_server import build_server_from_argv

    srv = build_server_from_argv(["--library", "clops.example_library.core", "--from-the-future"])
    assert srv.config.libraries == ["clops.example_library.core"]

    err = capsys.readouterr().err
    assert "--from-the-future" in err
    assert "older than whatever launched it" in err


def test_known_flags_still_take_effect_alongside_an_unknown_one():
    """Tolerating the unknown must not swallow the rest of the command line."""
    from clops import naming
    from clops.runtime.mcp_server import build_server_from_argv

    # `--server-name` mutates module-level naming state that other tests read,
    # and nothing here resets it automatically.
    original = naming.server_name()
    try:
        srv = build_server_from_argv(
            [
                "--server-name",
                "clops-support",
                "--nonsense",
                "--library",
                "clops.example_library.core",
            ]
        )
        assert srv.config.libraries == ["clops.example_library.core"]
        assert naming.server_name() == "clops-support"
    finally:
        naming.set_server_name(original)
