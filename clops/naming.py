"""Single source of truth for the MCP server name and the tool references derived from it.

Claude Code namespaces MCP tools by server name — a tool `complete` on a server
registered as `clops` is called as `mcp__clops__complete`. That prefix is what
keeps a locally-installed clops and a hosted one from colliding in the same
project, so the name cannot be a constant: it is chosen per project by
``clops init --server-name`` and must be echoed back by the running server
(``clops-server --server-name``) so dispatch prompts tell subagents the *right*
thing to call.

The *shape* of that reference is not universal either. `mcp__<server>__<tool>`
is a Claude Code convention, not part of MCP. Put clops behind a gateway and the
client sees something else entirely — IBM ContextForge re-exposes `complete` as
`clops-support-complete`: its own prefix, hyphens for underscores, no `mcp__`.
A dispatch prompt naming `mcp__clops__complete` there tells the subagent to call
a tool that is not on its list, and the run stalls at the first step. So the
pattern is configurable too (``clops-server --tool-pattern``), defaulting to the
Claude Code form because that is what the overwhelming majority of clients are.

Process-global, like the Op registry: one server per process, set once at
startup before any prompt is rendered.
"""

from __future__ import annotations

import re
import string

DEFAULT_SERVER_NAME = "clops"

#: How a client refers to one of our tools. Placeholders are ``{server}`` and
#: ``{name}``, plus ``_hyphenated`` variants of each for clients that rewrite
#: underscores. The default is the Claude Code convention.
DEFAULT_TOOL_PATTERN = "mcp__{server}__{name}"

_TOOL_PATTERN_FIELDS = frozenset(
    {"server", "name", "server_hyphenated", "name_hyphenated"}
)

# Conservative: what survives being embedded in an `mcp__<server>__<tool>`
# identifier without ambiguity. Double underscores are excluded because they are
# the delimiter itself — `mcp__a__b__c` would be unparseable.
_VALID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

_server_name = DEFAULT_SERVER_NAME
_tool_pattern = DEFAULT_TOOL_PATTERN


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


def qualify_server_name(name: str) -> str:
    """Guarantee ``clops`` appears in the server name.

    White-labelling is a naming concern, not an architectural one: a hosted
    instance can be called whatever the deployment wants, but the name should
    still say what runtime is underneath. Every clops-derived server is then
    recognisable — to a person reading a tool list, and to a grep — as speaking
    the same protocol, however many are installed side by side.

    So the caller supplies only the distinguishing part and we add the hint:

        acme-dev   -> clops-acme-dev
        support        -> clops-support
        clops          -> clops              (already says it)
        clops-support  -> clops-support      (idempotent; no double prefix)

    Idempotent, so a name can be qualified by `clops init` and re-qualified by
    the server it launches without drifting.
    """
    name = validate_server_name(name)
    if "clops" in name.lower():
        return name
    return f"{DEFAULT_SERVER_NAME}-{name}"


def set_server_name(name: str) -> None:
    """Set the process-wide server name. Call once, at startup."""
    global _server_name
    _server_name = qualify_server_name(name)


def server_name() -> str:
    return _server_name


def validate_tool_pattern(pattern: str) -> str:
    """Return ``pattern`` if it is a usable tool-reference template, else raise.

    Rejects unknown placeholders rather than letting them through. A typo like
    ``{tool}`` would otherwise surface as a KeyError from deep inside prompt
    rendering, or — worse, if it were merely ignored — as a prompt naming a tool
    that does not exist, which is the exact failure this pattern exists to fix.
    """
    pattern = (pattern or "").strip()
    if not pattern:
        raise ValueError("tool pattern cannot be empty")

    fields = {
        field
        for _, field, _, _ in string.Formatter().parse(pattern)
        if field is not None
    }
    unknown = fields - _TOOL_PATTERN_FIELDS
    if unknown:
        raise ValueError(
            f"unknown placeholder(s) {sorted(unknown)} in tool pattern {pattern!r}; "
            f"available: {sorted(_TOOL_PATTERN_FIELDS)}"
        )
    if not fields & {"name", "name_hyphenated"}:
        raise ValueError(
            f"tool pattern {pattern!r} must contain {{name}} or {{name_hyphenated}} — "
            "without it every tool renders to the same string"
        )
    return pattern


def set_tool_pattern(pattern: str) -> None:
    """Set the process-wide tool-reference pattern. Call once, at startup."""
    global _tool_pattern
    _tool_pattern = validate_tool_pattern(pattern)


def tool_pattern() -> str:
    return _tool_pattern


def tool(name: str) -> str:
    """The reference a client uses to call one of our tools.

    Not necessarily the tool's own name. What a client calls is decided by the
    client (or by a gateway in between), so this renders the configured pattern
    rather than assuming the Claude Code form.
    """
    return _tool_pattern.format(
        server=_server_name,
        server_hyphenated=_server_name.replace("_", "-"),
        name=name,
        name_hyphenated=name.replace("_", "-"),
    )
