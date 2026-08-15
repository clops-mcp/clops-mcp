"""Tests for .clops file reading and multi-library support."""

from __future__ import annotations

import json
import os
import signal
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from clops.runtime.clops import CLOPS_FILENAME, ClopsConfig, read_clops, read_clops_config


# ---- .clops reader ---------------------------------------------------


def test_read_clops_returns_empty_when_file_missing(tmp_path):
    assert read_clops(tmp_path) == []


def test_read_clops_reads_library_names(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text("my_ops\nshared_utils\n")
    assert read_clops(tmp_path) == ["my_ops", "shared_utils"]


def test_read_clops_ignores_comments_and_blanks(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text(
        "# Op libraries\n"
        "\n"
        "my_ops\n"
        "  # indented comment\n"
        "\n"
        "shared_utils\n"
    )
    assert read_clops(tmp_path) == ["my_ops", "shared_utils"]


def test_read_clops_strips_whitespace(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text("  my_ops  \n\tlib_b\t\n")
    assert read_clops(tmp_path) == ["my_ops", "lib_b"]


def test_read_clops_empty_file(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text("")
    assert read_clops(tmp_path) == []


def test_read_clops_comments_only(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text("# just a comment\n# another\n")
    assert read_clops(tmp_path) == []


# ---- .clops file-or-directory resolution -----------------------------


def test_read_clops_config_dir_reads_nested_settings(tmp_path):
    """A .clops directory reads settings from a nested .clops file."""
    clops_dir = tmp_path / CLOPS_FILENAME
    clops_dir.mkdir()
    (clops_dir / CLOPS_FILENAME).write_text(
        "my_ops\nshared_utils\n\n"
        "[runtime]\n"
        "output_contract = manifest\n"
    )
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == ["my_ops", "shared_utils"]
    assert cfg.settings == {"output_contract": "manifest"}


def test_read_clops_config_file_unchanged(tmp_path):
    """A plain .clops file behaves exactly as before."""
    (tmp_path / CLOPS_FILENAME).write_text(
        "my_ops\n\n[runtime]\noutput_contract = manifest\n"
    )
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == ["my_ops"]
    assert cfg.settings == {"output_contract": "manifest"}


def test_read_clops_config_dir_without_nested_file_is_empty(tmp_path):
    """A .clops directory with no nested settings file yields an empty config."""
    (tmp_path / CLOPS_FILENAME).mkdir()
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == []
    assert cfg.constants == {}
    assert cfg.settings == {}


def test_read_clops_config_neither_exists_is_empty(tmp_path):
    """Neither a .clops file nor directory yields an empty config."""
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == []
    assert cfg.constants == {}
    assert cfg.settings == {}


# ---- Multi-library server config ------------------------------------


def test_server_config_accepts_multiple_libraries():
    from clops.runtime.mcp_server import ServerConfig

    config = ServerConfig(libraries=["lib_a", "lib_b", "lib_c"])
    assert config.libraries == ["lib_a", "lib_b", "lib_c"]


def test_server_config_defaults_to_empty_list():
    from clops.runtime.mcp_server import ServerConfig

    config = ServerConfig()
    assert config.libraries == []


def test_build_server_reads_clops_when_no_library_flag(tmp_path):
    """When --library is not passed, server reads .clops from project dir."""
    from clops.runtime.mcp_server import build_server_from_argv

    (tmp_path / CLOPS_FILENAME).write_text("fake_lib_a\nfake_lib_b\n")
    srv = build_server_from_argv(["--project-dir", str(tmp_path)])
    # Libraries were read from .clops (they'll fail to import, but config is right).
    assert srv.config.libraries == ["fake_lib_a", "fake_lib_b"]


def test_build_server_library_flag_overrides_clops(tmp_path):
    """Explicit --library flags take precedence over .clops."""
    from clops.runtime.mcp_server import build_server_from_argv

    (tmp_path / CLOPS_FILENAME).write_text("clops_lib\n")
    srv = build_server_from_argv([
        "--project-dir", str(tmp_path),
        "--library", "explicit_lib",
    ])
    assert srv.config.libraries == ["explicit_lib"]


def test_build_server_multiple_library_flags(tmp_path):
    from clops.runtime.mcp_server import build_server_from_argv

    srv = build_server_from_argv([
        "--project-dir", str(tmp_path),
        "--library", "lib_a",
        "--library", "lib_b",
    ])
    assert srv.config.libraries == ["lib_a", "lib_b"]


# ---- Hook socket PID namespacing ------------------------------------


def test_hook_socket_path_includes_pid():
    from clops.runtime.mcp_server import hook_socket_path

    path = hook_socket_path(Path("/project"))
    assert f"hook-{os.getpid()}.sock" in path.name


def test_clean_stale_hook_sockets_removes_dead_pid(tmp_path):
    from clops.runtime.mcp_server import clean_stale_hook_sockets, runtime_state_dir

    state_dir = runtime_state_dir(tmp_path)
    state_dir.mkdir(parents=True)

    # Create a socket for a PID that definitely doesn't exist.
    stale = state_dir / "hook-99999999.sock"
    stale.touch()

    clean_stale_hook_sockets(tmp_path)
    assert not stale.exists()


def test_clean_stale_hook_sockets_keeps_live_pid(tmp_path):
    from clops.runtime.mcp_server import clean_stale_hook_sockets, runtime_state_dir

    state_dir = runtime_state_dir(tmp_path)
    state_dir.mkdir(parents=True)

    # Create a socket for our own PID (definitely alive).
    live = state_dir / f"hook-{os.getpid()}.sock"
    live.touch()

    clean_stale_hook_sockets(tmp_path)
    assert live.exists()
    live.unlink()  # cleanup


def test_clean_stale_hook_sockets_no_state_dir(tmp_path):
    """Does not error when state dir doesn't exist."""
    from clops.runtime.mcp_server import clean_stale_hook_sockets

    clean_stale_hook_sockets(tmp_path)  # no-op, no error


# ---- Hook broadcast --------------------------------------------------


def test_resolve_socket_paths_globs_pid_sockets(tmp_path):
    from clops.cli.hook import resolve_socket_paths

    state_dir = tmp_path / ".claude" / ".clops"
    state_dir.mkdir(parents=True)
    (state_dir / "hook-111.sock").touch()
    (state_dir / "hook-222.sock").touch()

    paths = resolve_socket_paths(
        env={"CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    names = {p.name for p in paths}
    assert "hook-111.sock" in names
    assert "hook-222.sock" in names


def test_resolve_socket_paths_falls_back_to_legacy(tmp_path):
    from clops.cli.hook import resolve_socket_paths

    state_dir = tmp_path / ".claude" / ".clops"
    state_dir.mkdir(parents=True)
    (state_dir / "hook.sock").touch()

    paths = resolve_socket_paths(
        env={"CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    assert len(paths) == 1
    assert paths[0].name == "hook.sock"


def test_resolve_socket_paths_prefers_explicit_env(tmp_path):
    from clops.cli.hook import resolve_socket_paths

    custom = tmp_path / "custom.sock"
    paths = resolve_socket_paths(
        env={"CLOPS_HOOK_SOCKET": str(custom)},
    )
    assert paths == [custom]


def test_run_broadcast_returns_first_decision(tmp_path):
    """Broadcast returns the first non-trivial decision."""
    from clops.cli.hook import run_broadcast

    # No sockets → fail-open.
    payload = json.dumps({"session_id": "p"}).encode("utf-8")
    out, code = run_broadcast(payload, [])
    assert out == "{}"
    assert code == 0


def test_run_broadcast_skips_missing_sockets(tmp_path):
    from clops.cli.hook import run_broadcast

    payload = json.dumps({"session_id": "p"}).encode("utf-8")
    out, code = run_broadcast(payload, [tmp_path / "nope.sock"])
    assert out == "{}"
    assert code == 0


# ---- .clops [constants] section --------------------------------------


def test_read_clops_config_libraries_only(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text("my_ops\nshared_utils\n")
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == ["my_ops", "shared_utils"]
    assert cfg.constants == {}


def test_read_clops_config_with_constants(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text(
        "my_ops\n\n"
        "[constants]\n"
        "user_id = wes-dev-123\n"
        "database = staging\n"
    )
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == ["my_ops"]
    assert cfg.constants == {"user_id": "wes-dev-123", "database": "staging"}


def test_read_clops_config_empty(tmp_path):
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == []
    assert cfg.constants == {}


def test_read_clops_config_comments_in_constants(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text(
        "lib_a\n"
        "[constants]\n"
        "# This is a comment\n"
        "key = value\n"
        "\n"
        "other = stuff\n"
    )
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == ["lib_a"]
    assert cfg.constants == {"key": "value", "other": "stuff"}


def test_read_clops_backwards_compat(tmp_path):
    """read_clops() still works and ignores [constants]."""
    (tmp_path / CLOPS_FILENAME).write_text(
        "my_ops\n[constants]\ndb = staging\n"
    )
    libs = read_clops(tmp_path)
    assert libs == ["my_ops"]


# ---- .clops [runtime] section ----------------------------------------


def test_read_clops_config_settings_default_empty(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text("my_ops\n")
    cfg = read_clops_config(tmp_path)
    assert cfg.settings == {}


def test_read_clops_config_parses_runtime_section(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text(
        "my_ops\n\n"
        "[runtime]\n"
        "# lighten complete() to a one-line manifest\n"
        "output_contract = manifest\n"
        "\n"
        "[constants]\n"
        "user_id = wes\n"
    )
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == ["my_ops"]
    assert cfg.settings == {"output_contract": "manifest"}
    assert cfg.constants == {"user_id": "wes"}


# ---- .clops [system_prompt] section ----------------------------------


def test_read_clops_config_system_prompt_default_none(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text("my_ops\n")
    cfg = read_clops_config(tmp_path)
    assert cfg.system_prompt is None


def test_read_clops_config_parses_system_prompt(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text(
        "my_ops\n\n"
        "[system_prompt]\n"
        "When you dispatch agents, consider the skill of the task\n"
        "for the level of agent necessary.\n"
    )
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == ["my_ops"]
    assert cfg.system_prompt == (
        "When you dispatch agents, consider the skill of the task\n"
        "for the level of agent necessary."
    )


def test_read_clops_config_system_prompt_preserves_prose(tmp_path):
    """Blank lines and '#' headings inside the body are content, not comments."""
    (tmp_path / CLOPS_FILENAME).write_text(
        "[system_prompt]\n"
        "# Dispatch policy\n"
        "\n"
        "Right-size the agent to the task.\n"
    )
    cfg = read_clops_config(tmp_path)
    assert cfg.system_prompt == (
        "# Dispatch policy\n"
        "\n"
        "Right-size the agent to the task."
    )


def test_read_clops_config_system_prompt_closed_by_next_section(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text(
        "[system_prompt]\n"
        "Guidance line.\n"
        "[constants]\n"
        "user_id = wes\n"
    )
    cfg = read_clops_config(tmp_path)
    assert cfg.system_prompt == "Guidance line."
    assert cfg.constants == {"user_id": "wes"}


def test_read_clops_config_empty_system_prompt_is_none(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text(
        "[system_prompt]\n\n\n[constants]\nk = v\n"
    )
    cfg = read_clops_config(tmp_path)
    assert cfg.system_prompt is None
    assert cfg.constants == {"k": "v"}


def test_system_prompt_surfaced_on_start_payload():
    """A configured system prompt rides the first dispatch payload of a run."""
    from clops import Concept, Op
    from clops.registry import registry
    from clops.runtime import Runtime

    registry.clear()

    class X(Concept):
        description = "x"

    class Y(Concept):
        description = "y"

    class Worker(Op):
        Input = X
        Output = Y
        Intent = "Work"
        Meta = "Test."
        entry = True

    rt = Runtime()
    rt._system_prompt = "Right-size the agent to the task."
    d = rt.start("Worker", "input", enforce_entry=True)
    assert d["action"] == "dispatch"
    assert d["system_prompt"] == "Right-size the agent to the task."

    registry.clear()


def test_default_system_prompt_surfaced_when_unconfigured():
    """A fresh Runtime carries the built-in default and surfaces it."""
    from clops import Concept, Op
    from clops.registry import registry
    from clops.runtime import Runtime
    from clops.runtime.core import DEFAULT_SYSTEM_PROMPT

    registry.clear()

    class X(Concept):
        description = "x"

    class Y(Concept):
        description = "y"

    class Worker(Op):
        Input = X
        Output = Y
        Intent = "Work"
        Meta = "Test."
        entry = True

    rt = Runtime()
    assert rt._system_prompt == DEFAULT_SYSTEM_PROMPT
    d = rt.start("Worker", "input", enforce_entry=True)
    assert d["system_prompt"] == DEFAULT_SYSTEM_PROMPT

    registry.clear()


def test_no_system_prompt_key_when_suppressed():
    from clops import Concept, Op
    from clops.registry import registry
    from clops.runtime import Runtime

    registry.clear()

    class X(Concept):
        description = "x"

    class Y(Concept):
        description = "y"

    class Worker(Op):
        Input = X
        Output = Y
        Intent = "Work"
        Meta = "Test."
        entry = True

    rt = Runtime()
    rt._system_prompt = None  # explicit suppression
    d = rt.start("Worker", "input", enforce_entry=True)
    assert "system_prompt" not in d

    registry.clear()


def test_configured_system_prompt_overrides_default_at_boot(tmp_path):
    """A [system_prompt] section replaces DEFAULT_SYSTEM_PROMPT on the Runtime."""
    from clops.runtime.core import DEFAULT_SYSTEM_PROMPT
    from clops.runtime.mcp_server import build_server_from_argv

    (tmp_path / CLOPS_FILENAME).write_text(
        "[system_prompt]\nProject-specific dispatch guidance.\n"
    )
    srv = build_server_from_argv(["--project-dir", str(tmp_path)])
    assert srv.runtime._system_prompt == "Project-specific dispatch guidance."
    assert srv.runtime._system_prompt != DEFAULT_SYSTEM_PROMPT


def test_boot_keeps_default_when_no_system_prompt_section(tmp_path):
    from clops.runtime.core import DEFAULT_SYSTEM_PROMPT
    from clops.runtime.mcp_server import build_server_from_argv

    (tmp_path / CLOPS_FILENAME).write_text("my_ops\n[constants]\nk = v\n")
    srv = build_server_from_argv(["--project-dir", str(tmp_path)])
    assert srv.runtime._system_prompt == DEFAULT_SYSTEM_PROMPT


# ---- module @ source syntax ------------------------------------------


def test_read_clops_config_with_path_source(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text(
        "work_ops @ /home/me/work-ops\n"
        "plain_lib\n"
    )
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == ["work_ops", "plain_lib"]
    assert cfg.sources == ["/home/me/work-ops"]
    assert cfg.entries[0].module == "work_ops"
    assert cfg.entries[0].source == "/home/me/work-ops"
    assert cfg.entries[1].source is None


def test_read_clops_config_with_git_source(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text(
        "team_ops @ git+https://github.com/company/team-ops\n"
    )
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == ["team_ops"]
    assert cfg.sources == ["git+https://github.com/company/team-ops"]


def test_read_clops_config_tilde_expanded(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text(
        "my_ops @ ~/work/my-ops\n"
    )
    cfg = read_clops_config(tmp_path)
    # ~ should be expanded to the home directory.
    assert not cfg.sources[0].startswith("~")
    assert cfg.entries[0].module == "my_ops"


def test_read_clops_config_mixed_plain_and_sourced(tmp_path):
    (tmp_path / CLOPS_FILENAME).write_text(
        "clops.example_library.core\n"
        "work_ops @ /opt/work-ops\n"
        "shared @ git+https://github.com/co/shared\n"
        "\n"
        "[constants]\n"
        "env = production\n"
    )
    cfg = read_clops_config(tmp_path)
    assert cfg.libraries == ["clops.example_library.core", "work_ops", "shared"]
    assert cfg.sources == ["/opt/work-ops", "git+https://github.com/co/shared"]
    assert cfg.constants == {"env": "production"}


def test_read_clops_backwards_compat_with_sources(tmp_path):
    """read_clops() returns module names even for sourced entries."""
    (tmp_path / CLOPS_FILENAME).write_text(
        "work_ops @ /home/me/work-ops\nplain_lib\n"
    )
    libs = read_clops(tmp_path)
    assert libs == ["work_ops", "plain_lib"]


def test_constants_injected_into_runtime():
    """Constants from .clops are registered as read-only stores on each run."""
    from clops import Concept, Op, Store
    from clops.registry import registry
    from clops.runtime import Runtime

    registry.clear()

    class X(Concept):
        description = "x"

    class Y(Concept):
        description = "y"

    class Worker(Op):
        Input = X
        Output = Y
        Intent = "Work"
        Meta = "Test."
        entry = True

    rt = Runtime()
    rt._project_constants = {"user_id": "wes-123", "database": "staging"}
    d = rt.start("Worker", "input", enforce_entry=True)
    sm = rt.get_state_manager(d["run_id"])
    assert sm is not None
    assert sm.execute("user_id", "get") == "wes-123"
    assert sm.execute("database", "get") == "staging"

    exec_id = next(iter(rt.get_run(d["run_id"]).pending_executions))
    with pytest.raises(Exception, match="read-only"):
        rt.state(exec_id, "user_id", "set", value="hacked")

    registry.clear()
