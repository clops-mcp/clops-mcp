""".clops file reader.

A `.clops` file is a project-level manifest listing the Op libraries
that should be loaded when the MCP server starts, plus optional
project-level constants.

Format::

    # Plain module names (already importable).
    my_ops
    clops.stdlib.core

    # Path source — installed via uv --with.
    work_ops @ ~/work/work-ops
    shared_ops @ /opt/shared/shared-ops

    # Git source — installed via uv --with.
    team_ops @ git+https://github.com/company/team-ops

    [constants]
    user_id = wes-dev-123
    database = support_staging

The ``module @ source`` syntax tells clops that the library needs
to be installed (via ``uv run --with source``) before it can be
imported. Plain module names are assumed to be already importable.

The server resolves the project directory at boot (via --project-dir,
$CLAUDE_PROJECT_DIR, or cwd) and reads `.clops` from there.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

CLOPS_FILENAME = ".clops"


@dataclass
class LibraryEntry:
    """One library from the ``.clops`` file."""
    module: str                 # importable module name
    source: str | None = None   # path or git URL, or None if plain module

    @property
    def needs_install(self) -> bool:
        return self.source is not None


@dataclass
class ClopsConfig:
    """Parsed contents of a ``.clops`` file."""
    entries: list[LibraryEntry] = field(default_factory=list)
    constants: dict[str, str] = field(default_factory=dict)
    settings: dict[str, str] = field(default_factory=dict)
    system_prompt: str | None = None

    @property
    def libraries(self) -> list[str]:
        """Module names only (for --library flags / importlib)."""
        return [e.module for e in self.entries]

    @property
    def sources(self) -> list[str]:
        """Path/git sources that need uv --with (for .mcp.json generation)."""
        return [e.source for e in self.entries if e.source is not None]


def _parse_library_line(line: str) -> LibraryEntry:
    """Parse a library line, handling ``module @ source`` syntax."""
    if " @ " in line:
        module, _, source = line.partition(" @ ")
        source = source.strip()
        # Expand ~ in paths.
        if source.startswith("~"):
            source = os.path.expanduser(source)
        return LibraryEntry(module=module.strip(), source=source)
    return LibraryEntry(module=line)


def _resolve_clops_settings_path(project_dir: Path) -> Path | None:
    """Locate the ``.clops`` settings file within ``project_dir``.

    ``project_dir/.clops`` may be either a plain file (today's behavior) or
    a directory. If it's a directory, the settings live in a ``.clops`` file
    nested inside it (``project_dir/.clops/.clops``). Returns the path to the
    settings file to read, or ``None`` if no settings file exists.
    """
    clops_path = project_dir / CLOPS_FILENAME
    if clops_path.is_dir():
        nested = clops_path / CLOPS_FILENAME
        return nested if nested.is_file() else None
    return clops_path if clops_path.is_file() else None


def read_clops(project_dir: Path) -> list[str]:
    """Read library import paths from a ``.clops`` file.

    Returns an empty list if the file doesn't exist.
    Backwards-compatible: returns just module names.
    """
    return read_clops_config(project_dir).libraries


def read_clops_config(project_dir: Path) -> ClopsConfig:
    """Read the full ``.clops`` config including constants and sources.

    Lines before any ``[section]`` header are library entries.
    The ``[constants]`` section contains ``key = value`` pairs.
    The ``[runtime]`` section contains ``key = value`` runtime settings
    (e.g. ``output_contract = manifest``).
    The ``[system_prompt]`` section is free-form prose surfaced to the
    orchestrator at the start of every run — standing guidance for how
    the main execution flow manages the run's dispatches. Its body is
    captured verbatim (blank lines and ``#`` markdown headings are
    content, not comments) until the next ``[section]`` header.
    Comments (``#``) and blank lines are ignored in every other section.

    The ``.clops`` entry in ``project_dir`` may be a plain file (read
    directly) or a directory (settings are read from a ``.clops`` file
    nested inside it). Returns an empty config when no settings file exists.
    """
    clops_path = _resolve_clops_settings_path(project_dir)
    if clops_path is None:
        return ClopsConfig()

    entries: list[LibraryEntry] = []
    constants: dict[str, str] = {}
    settings: dict[str, str] = {}
    system_prompt_lines: list[str] = []
    current_section: str | None = None

    for line in clops_path.read_text().splitlines():
        stripped = line.strip()

        # Section header? Checked before comment/blank skipping so it still
        # closes the free-form [system_prompt] body when one is open.
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1].strip().lower()
            continue

        # The system_prompt body is prose: keep raw lines (including blanks
        # and '#' headings) so the author's formatting survives intact.
        if current_section == "system_prompt":
            system_prompt_lines.append(line)
            continue

        if not stripped or stripped.startswith("#"):
            continue

        if current_section is None:
            entries.append(_parse_library_line(stripped))
        elif current_section == "constants":
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                constants[key.strip()] = value.strip()
        elif current_section == "runtime":
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                settings[key.strip()] = value.strip()

    system_prompt = "\n".join(system_prompt_lines).strip() or None

    return ClopsConfig(
        entries=entries,
        constants=constants,
        settings=settings,
        system_prompt=system_prompt,
    )
