"""Tests for `clops init`."""

from __future__ import annotations

import json
from pathlib import Path

from clops.cli.init import (
    DEFAULT_INSTALL_SPEC,
    GITIGNORE_LINE,
    HOOK_COMMAND,
    MCP_SERVER_NAME,
    build_mcp_json,
    build_settings_patch,
    init_project,
    install_spec,
    merge_settings,
)


# ---- build_settings_patch (hooks only) -------------------------------


def test_build_settings_patch_has_hook():
    patch = build_settings_patch()
    entry = patch["hooks"]["SubagentStop"][0]
    assert "matcher" in entry
    assert entry["hooks"][0]["command"] == HOOK_COMMAND
    assert "mcpServers" not in patch


# ---- build_mcp_json --------------------------------------------------


def test_build_mcp_json_plain_libraries():
    mcp = build_mcp_json(["my_company.ops"], [])
    server = mcp["mcpServers"][MCP_SERVER_NAME]
    assert server["command"] == "uvx"
    # `uvx --from <install-spec> clops-server ...`
    assert server["args"][0] == "--from"
    assert server["args"][1] == install_spec()
    assert "clops-server" in server["args"]
    assert "--library" in server["args"]
    assert "my_company.ops" in server["args"]
    assert "--with" not in server["args"]


def test_install_spec_defaults_to_the_pypi_distribution(monkeypatch):
    """A generated project must be installable by someone with nothing but uv.

    This defaulted to `git+https://github.com/clops-mcp/clops-mcp` while the
    package was unpublished, which quietly required git — and, while the repo
    was private, repo access as well. `clops-mcp` is the distribution name; the
    obvious guess, `clops`, is an unrelated project on PyPI.
    """
    monkeypatch.delenv("CLOPS_INSTALL_SPEC", raising=False)
    assert install_spec() == DEFAULT_INSTALL_SPEC == "clops-mcp"
    assert not install_spec().startswith("git+")


def test_install_spec_env_override(monkeypatch):
    monkeypatch.setenv("CLOPS_INSTALL_SPEC", "clops-mcp==9.9.9")
    assert install_spec() == "clops-mcp==9.9.9"
    # And it flows through to the generated MCP server args + hook command.
    server = build_mcp_json(["my_ops"], [])["mcpServers"][MCP_SERVER_NAME]
    assert server["args"][1] == "clops-mcp==9.9.9"


def test_hook_command_targets_install_spec():
    assert HOOK_COMMAND.startswith("uvx --from ")
    assert HOOK_COMMAND.endswith("clops-hook")


def test_build_mcp_json_with_sources():
    mcp = build_mcp_json(["work_ops"], ["/home/me/work-ops"])
    args = mcp["mcpServers"][MCP_SERVER_NAME]["args"]
    assert "--with" in args
    assert "/home/me/work-ops" in args
    assert "--library" in args
    assert "work_ops" in args


def test_build_mcp_json_multiple_sources():
    mcp = build_mcp_json(
        ["ops_a", "ops_b"],
        ["/path/a", "git+https://github.com/co/ops-b"],
    )
    args = mcp["mcpServers"][MCP_SERVER_NAME]["args"]
    with_indices = [i for i, a in enumerate(args) if a == "--with"]
    assert len(with_indices) == 2
    lib_indices = [i for i, a in enumerate(args) if a == "--library"]
    assert len(lib_indices) == 2


# ---- merge_settings (hooks only) ------------------------------------


def _all_subagent_stop_commands(merged: dict) -> list[str]:
    """Flatten commands from both legacy flat entries and matcher+hooks entries."""
    out: list[str] = []
    for h in merged["hooks"]["SubagentStop"]:
        if "command" in h:
            out.append(h["command"])
        for inner in h.get("hooks", []) or []:
            if "command" in inner:
                out.append(inner["command"])
    return out


def test_merge_settings_appends_hook_only_once():
    """Re-running init after upgrade: legacy flat hook is recognized, not duplicated."""
    existing = {
        "hooks": {
            "SubagentStop": [{"type": "command", "command": HOOK_COMMAND}],
            "PreToolUse": [{"type": "command", "command": "user-hook"}],
        }
    }
    merged = merge_settings(existing, build_settings_patch())
    cmds = _all_subagent_stop_commands(merged)
    assert cmds.count(HOOK_COMMAND) == 1
    assert merged["hooks"]["PreToolUse"][0]["command"] == "user-hook"


def test_merge_settings_appends_when_other_hook_exists():
    existing = {"hooks": {"SubagentStop": [{"type": "command", "command": "other-hook"}]}}
    merged = merge_settings(existing, build_settings_patch())
    cmds = _all_subagent_stop_commands(merged)
    assert "other-hook" in cmds
    assert HOOK_COMMAND in cmds


def test_merge_settings_preserves_user_keys():
    existing = {"userKey": {"keep": True}, "hooks": {}}
    merged = merge_settings(existing, build_settings_patch())
    assert merged["userKey"] == {"keep": True}


# ---- init_project (full integration) ---------------------------------


def test_init_project_writes_expected_files(tmp_path):
    written = init_project(tmp_path, libraries=["pkg.x"])

    # .clops
    clops_path = tmp_path / ".clops"
    assert written["clops"] == clops_path
    assert "pkg.x" in clops_path.read_text().splitlines()

    # .mcp.json
    mcp_path = tmp_path / ".mcp.json"
    assert written["mcp_json"] == mcp_path
    mcp = json.loads(mcp_path.read_text())
    assert mcp["mcpServers"][MCP_SERVER_NAME]["command"] == "uvx"
    assert "--library" in mcp["mcpServers"][MCP_SERVER_NAME]["args"]

    # settings.json (hooks only, no mcpServers)
    settings_path = tmp_path / ".claude" / "settings.json"
    assert written["settings"] == settings_path
    settings = json.loads(settings_path.read_text())
    assert "mcpServers" not in settings
    entry = settings["hooks"]["SubagentStop"][0]
    assert entry["hooks"][0]["command"] == HOOK_COMMAND

    # clops-executor.md
    fe_path = tmp_path / ".claude" / "agents" / "clops-executor.md"
    assert written["clops_executor"] == fe_path
    assert fe_path.exists()

    # gitignore
    assert "gitignore" in written
    gi_text = (tmp_path / ".gitignore").read_text()
    assert GITIGNORE_LINE in gi_text.splitlines()

    # skill IS installed by default (self-contained project)
    skill_path = tmp_path / ".claude" / "skills" / "clops-orchestration" / "SKILL.md"
    assert written["skill"] == skill_path
    assert skill_path.exists()


def test_init_project_with_source_library(tmp_path):
    """Library with @ source generates --with in .mcp.json."""
    written = init_project(tmp_path, libraries=["work_ops @ /home/me/work-ops"])

    mcp = json.loads((tmp_path / ".mcp.json").read_text())
    args = mcp["mcpServers"][MCP_SERVER_NAME]["args"]
    assert "--with" in args
    assert "/home/me/work-ops" in args
    assert "--library" in args
    assert "work_ops" in args

    # .clops has the full entry
    clops_text = (tmp_path / ".clops").read_text()
    assert "work_ops @ /home/me/work-ops" in clops_text


def test_init_project_with_git_source(tmp_path):
    written = init_project(tmp_path, libraries=["team_ops @ git+https://github.com/co/ops"])

    mcp = json.loads((tmp_path / ".mcp.json").read_text())
    args = mcp["mcpServers"][MCP_SERVER_NAME]["args"]
    assert "git+https://github.com/co/ops" in args
    assert "team_ops" in args


def test_init_project_no_skill_flag_skips_skill(tmp_path):
    written = init_project(tmp_path, libraries=["pkg.x"], write_skill_file=False)
    skill_path = tmp_path / ".claude" / "skills" / "clops-orchestration" / "SKILL.md"
    assert "skill" not in written
    assert not skill_path.exists()


def test_init_project_does_not_duplicate_gitignore_entry(tmp_path):
    (tmp_path / ".gitignore").write_text(f"{GITIGNORE_LINE}\nother\n")
    init_project(tmp_path, libraries=["pkg.x"])
    text = (tmp_path / ".gitignore").read_text()
    assert text.count(GITIGNORE_LINE) == 1


def test_init_project_re_run_changes_mcp_json(tmp_path):
    init_project(tmp_path, libraries=["first.lib"])
    init_project(tmp_path, libraries=["second.lib"])
    mcp = json.loads((tmp_path / ".mcp.json").read_text())
    args = mcp["mcpServers"][MCP_SERVER_NAME]["args"]
    assert "second.lib" in args
    # .mcp.json is overwritten each time (not merged)


def test_init_project_preserves_unrelated_settings(tmp_path):
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"env": {"FOO": "bar"}}))
    init_project(tmp_path, libraries=["pkg.x"])
    settings = json.loads(settings_path.read_text())
    assert settings["env"] == {"FOO": "bar"}
