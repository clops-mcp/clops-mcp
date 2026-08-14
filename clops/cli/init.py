"""`clops init` — set up a project for the clops runtime.

What it writes (non-destructively; merges with existing files):
    .mcp.json                        — clops MCP server (uvx --from <install spec>)
    .claude/settings.json            — SubagentStop hook
    .claude/agents/clops-executor.md  — the executor subagent
    .claude/skills/clops-orchestration/SKILL.md — the dispatch relay skill
    .clops                           — the project's Op libraries
    .gitignore                       — append `.claude/.clops/`

`init` writes a **fully self-contained** project: the orchestration skill and
executor agent are copied in so the project works without the clops plugin
installed. (The plugin is optional and additive — it surfaces the same skills
globally. Pass `--no-skill` to skip the skill copy if you rely on the plugin.)

What `init` does NOT do:
    - Touch authoring — this is a user-mode install. Author mode is just
      `pip install clops` in a Python repo.
    - Install clops itself. It assumes you've done that already
      (e.g. `uv tool install clops`).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Optional

# ---------- Paths to the bundled plugin assets -----------------------

_PKG_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = _PKG_ROOT / "_plugin"
CLOPS_EXECUTOR_SRC = PLUGIN_DIR / "agents" / "clops-executor.md"
SKILL_SRC = PLUGIN_DIR / "skills" / "clops-orchestration" / "SKILL.md"


# ---------- Config snippets ------------------------------------------


MCP_SERVER_NAME = "clops"
PYPI_NAME = "clops-mcp"
# clops-mcp is not on PyPI yet — the runtime installs straight from the
# (private) GitHub repo. Override with CLOPS_INSTALL_SPEC to change the source,
# e.g. an SSH URL (`git+ssh://git@github.com/wesley-harding/clops`), a pinned
# ref (`git+https://github.com/wesley-harding/clops@v0.2.0`), or the PyPI
# package (`clops-mcp==0.3.0`) once it's published.
GIT_REPO = "git+https://github.com/wesley-harding/clops"
GITIGNORE_LINE = ".claude/.clops/"


def install_spec() -> str:
    """The ``uvx --from`` target for the clops runtime.

    Defaults to the GitHub repo (default branch) since ``clops-mcp`` isn't
    published to PyPI yet. ``CLOPS_INSTALL_SPEC`` overrides it entirely — set it
    to an SSH URL, a pinned ``@<ref>``, or the PyPI spec once published. Using a
    single source keeps a project's generated MCP server + hook on the same
    clops build.
    """
    override = os.environ.get("CLOPS_INSTALL_SPEC")
    if override:
        return override
    return GIT_REPO


HOOK_COMMAND = f"uvx --from {install_spec()} clops-hook"


def build_settings_patch() -> dict:
    """The settings.json fragment we merge in (hooks only).

    Uses Claude Code's matcher+hooks shape. SubagentStop fires for every
    subagent stop, so the matcher is empty (match all).
    """
    return {
        "hooks": {
            "SubagentStop": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": HOOK_COMMAND}],
                }
            ],
        },
    }


def build_mcp_json(libraries: list[str], sources: list[str]) -> dict:
    """Build .mcp.json that runs the clops MCP server via uvx.

    Using ``uvx --from clops-mcp`` works regardless of how clops itself was
    installed (plugin, pip, uv tool install, or not at all) — nothing needs to
    be on PATH. Library sources are pulled into the same run env via repeated
    ``--with`` flags.
    """
    args = ["--from", install_spec()]
    for src in sources:
        args.extend(["--with", src])
    args.append("clops-server")
    for lib in libraries:
        args.extend(["--library", lib])
    return {
        "mcpServers": {
            MCP_SERVER_NAME: {
                "type": "stdio",
                "command": "uvx",
                "args": args,
            }
        }
    }


# ---------- File operations (idempotent, merging) --------------------


def merge_settings(existing: dict, patch: dict) -> dict:
    """Merge our patch into existing settings.json without clobbering.

    Rules:
        - Our SubagentStop hook is appended if not present by command.
        - All other user keys are left alone.
        - MCP server config goes in .mcp.json, not here.

    SubagentStop entries follow Claude Code's matcher+hooks shape:
    each entry has a ``matcher`` and a nested ``hooks`` list. We look
    for HOOK_COMMAND inside any nested ``hooks`` array — and also in
    the legacy flat shape, so re-running ``clops init`` after an
    upgrade doesn't double-write the hook.
    """
    out = dict(existing)

    hooks = dict(out.get("hooks", {}))
    subagent_stop = list(hooks.get("SubagentStop", []))

    def _is_clops_hook(cmd: object) -> bool:
        # Match on the `clops-hook` entrypoint, not the exact string, so a
        # version-pinned re-run (clops-mcp==0.1.0 -> ==0.2.0) dedupes instead
        # of stacking a second hook.
        return isinstance(cmd, str) and "clops-hook" in cmd

    def _has_our_hook(entry: dict) -> bool:
        if _is_clops_hook(entry.get("command")):
            return True
        for inner in entry.get("hooks", []) or []:
            if isinstance(inner, dict) and _is_clops_hook(inner.get("command")):
                return True
        return False

    has_ours = any(isinstance(h, dict) and _has_our_hook(h) for h in subagent_stop)
    if not has_ours:
        subagent_stop.extend(patch["hooks"]["SubagentStop"])
    hooks["SubagentStop"] = subagent_stop
    out["hooks"] = hooks

    return out


def write_clops(project_dir: Path, libraries: list[str]) -> Path:
    """Write a ``.clops`` file listing the project's Op libraries."""
    from clops.runtime.clops import CLOPS_FILENAME

    clops_path = project_dir / CLOPS_FILENAME
    existing: list[str] = []
    if clops_path.exists():
        for line in clops_path.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                existing.append(stripped)
    merged = list(dict.fromkeys(existing + libraries))  # dedupe, preserve order
    content = "# Op libraries for this project.\n"
    for lib in merged:
        content += lib + "\n"
    clops_path.write_text(content)
    return clops_path


def write_settings(project_dir: Path) -> Path:
    """Write hooks to .claude/settings.json (MCP config goes in .mcp.json)."""
    settings_path = project_dir / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            raise RuntimeError(
                f"{settings_path} exists but is not valid JSON. "
                "Fix it before re-running `clops init`."
            )

    merged = merge_settings(existing, build_settings_patch())
    settings_path.write_text(json.dumps(merged, indent=2) + "\n")
    return settings_path


def write_mcp_json(project_dir: Path, libraries: list[str], sources: list[str]) -> Path:
    """Write .mcp.json with MCP server config (uv run + --with for sources)."""
    mcp_path = project_dir / ".mcp.json"
    mcp_data = build_mcp_json(libraries, sources)
    mcp_path.write_text(json.dumps(mcp_data, indent=2) + "\n")
    return mcp_path


def write_clops_executor(project_dir: Path) -> Path:
    dest = project_dir / ".claude" / "agents" / "clops-executor.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CLOPS_EXECUTOR_SRC, dest)
    return dest


def write_skill(project_dir: Path) -> Path:
    dest = project_dir / ".claude" / "skills" / "clops-orchestration" / "SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SKILL_SRC, dest)
    return dest


def update_gitignore(project_dir: Path) -> Optional[Path]:
    path = project_dir / ".gitignore"
    existing = path.read_text() if path.exists() else ""
    if GITIGNORE_LINE in existing.splitlines():
        return None
    suffix = "" if (not existing or existing.endswith("\n")) else "\n"
    new = existing + suffix + GITIGNORE_LINE + "\n"
    path.write_text(new)
    return path


# ---------- Subcommand entry point ------------------------------------


def init_project(project_dir: Path, libraries: list[str], *, write_skill_file: bool = True) -> dict[str, Path]:
    """Write all init artifacts. Returns a map of what was written."""
    from clops.runtime.clops import _parse_library_line

    project_dir = project_dir.resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    # Parse library entries to separate modules from sources.
    entries = [_parse_library_line(lib) for lib in libraries]
    modules = [e.module for e in entries]
    sources = [e.source for e in entries if e.source is not None]

    written: dict[str, Path] = {}
    written["clops"] = write_clops(project_dir, libraries)
    written["mcp_json"] = write_mcp_json(project_dir, modules, sources)
    written["settings"] = write_settings(project_dir)
    written["clops_executor"] = write_clops_executor(project_dir)
    if write_skill_file:
        written["skill"] = write_skill(project_dir)
    gi = update_gitignore(project_dir)
    if gi is not None:
        written["gitignore"] = gi
    return written


def add_arguments(parser) -> None:
    """Register this subcommand's flags on an argparse subparser."""
    parser.add_argument(
        "--library",
        action="append",
        default=[],
        required=True,
        help="Python import path of an Op library (repeatable).",
    )
    parser.add_argument("--project-dir", default=".", help="Project directory (default: cwd).")
    parser.add_argument(
        "--no-skill",
        action="store_true",
        help="Skip copying the clops-orchestration skill (use if you rely on the installed plugin for it).",
    )


def run(ns) -> int:
    """Handler invoked by the subcommand dispatcher."""
    written = init_project(
        Path(ns.project_dir),
        libraries=ns.library,
        write_skill_file=not ns.no_skill,
    )
    for key, path in written.items():
        print(f"wrote {key}: {path}")
    return 0
