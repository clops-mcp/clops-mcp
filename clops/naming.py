"""Single source of truth for the MCP server name and the tool references derived from it.

Claude Code namespaces MCP tools by server name — a tool `complete` on a server
registered as `clops` is called as `mcp__clops__complete`. That prefix is what
keeps a locally-installed clops and a hosted one from colliding in the same
project, so the name cannot be a constant: it is chosen per project by
``clops init --server-name`` and must be echoed back by the running server
(``clops-server --server-name``) so dispatch prompts tell subagents the *right*
thing to call.

Process-global, like the Op registry: one server per process, set once at
startup before any prompt is rendered.
"""

from __future__ import annotations

import re

DEFAULT_SERVER_NAME = "clops"

# Conservative: what survives being embedded in an `mcp__<server>__<tool>`
# identifier without ambiguity. Double underscores are excluded because they are
# the delimiter itself — `mcp__a__b__c` would be unparseable.
_VALID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

_server_name = DEFAULT_SERVER_NAME


def validate_server_name(name: str) -> str:
    """Return ``name`` if usable as an MCP server name, else raise ValueError."""
    name = (name or "").strip()
    if not _VALID_NAME.match(name):
        raise ValueError(
            f"invalid MCP server name {name!r}: must start with a letter or digit "
            "and contain only letters, digits, hyphens, and single underscores"
        )
    if "__" in name:
        raise ValueError(
            f"invalid MCP server name {name!r}: '__' is the tool-name delimiter "
            "(mcp__<server>__<tool>) and cannot appear in the server name"
        )
    return name


def set_server_name(name: str) -> None:
    """Set the process-wide server name. Call once, at startup."""
    global _server_name
    _server_name = validate_server_name(name)


def server_name() -> str:
    return _server_name


def tool(name: str) -> str:
    """The fully-qualified reference a client uses to call one of our tools."""
    return f"mcp__{_server_name}__{name}"
