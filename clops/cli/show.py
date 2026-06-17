"""`clops show <pkg>` — static inspector for an Op library.

Prints the library's shape — Ops (entry markers + composition body
trees), Snippets, Tools — so a reader can orient in an unfamiliar
library without opening every file.
"""

from __future__ import annotations

import sys
from typing import Any

from clops.combinators import describe
from clops.registry import registry
from clops.snippet import Snippet, SnippetRole


INDENT = "  "


def add_arguments(parser) -> None:
    parser.add_argument(
        "library",
        help="Python import path of the Op library to inspect (e.g. my_company.ops).",
    )


def run(ns) -> int:
    try:
        # Use the linter's re-import so subpackages are recursively imported
        # and the registry is populated freshly.
        from clops.linter import _reimport_recursive
        _reimport_recursive(ns.library)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[FATAL] Failed to import {ns.library!r}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    ops = registry.ops()
    snippets = registry.snippets()
    tools = registry.tools()

    if not ops:
        print(
            f"No Ops registered in {ns.library!r}. "
            "Did you forget to import the ops module in __init__.py?"
        )
        return 0

    _print_ops_section(ops)
    if snippets:
        print()
        _print_snippets_section(snippets)
    if tools:
        print()
        _print_tools_section(tools)
    return 0


# ---------- Section renderers ---------------------------------------


def _print_ops_section(ops: dict[str, type]) -> None:
    print(f"Ops ({len(ops)}):")
    # Entry-tagged Ops surface first.
    def sort_key(item):
        name, op_cls = item
        return (0 if getattr(op_cls, "entry", False) else 1, name)

    for _, op_cls in sorted(ops.items(), key=sort_key):
        for line in _format_op(op_cls):
            print(line)


def _format_op(op_cls) -> list[str]:
    name = op_cls.__name__
    lines: list[str] = []
    entry_marker = "  [ENTRY]" if getattr(op_cls, "entry", False) else ""
    lines.append(f"{INDENT}{name}{entry_marker}")

    input_cls = getattr(op_cls, "Input", None)
    output_cls = getattr(op_cls, "Output", None)
    input_name = input_cls.__name__ if isinstance(input_cls, type) else repr(input_cls)
    output_name = output_cls.__name__ if isinstance(output_cls, type) else repr(output_cls)
    lines.append(f"{INDENT * 2}Input:    {input_name}")
    lines.append(f"{INDENT * 2}Output:   {output_name}")

    body = getattr(op_cls, "body", None)
    if body is not None:
        lines.append(f"{INDENT * 2}body:")
        for nested_indent, label in describe(body):
            lines.append(f"{INDENT * 3}{INDENT * nested_indent}└─ {label}")

    uses_snippets = [u.id for u in getattr(op_cls, "Uses", []) if isinstance(u, Snippet)]
    if uses_snippets:
        lines.append(f"{INDENT * 2}Uses:     {', '.join(uses_snippets)}")

    requires_roles = [r.role for r in getattr(op_cls, "Requires", []) if isinstance(r, SnippetRole)]
    if requires_roles:
        lines.append(f"{INDENT * 2}Requires: {', '.join(requires_roles)}")

    tool_names = [t.name for t in getattr(op_cls, "Tools", [])]
    if tool_names:
        lines.append(f"{INDENT * 2}Tools:    {', '.join(tool_names)}")

    return lines


def _print_snippets_section(snippets: dict[str, Snippet]) -> None:
    print(f"Snippets ({len(snippets)}):")
    for sid in sorted(snippets.keys()):
        s = snippets[sid]
        role = f" role={s.role}" if s.role else ""
        preview = _truncate(s.content, 60)
        print(f'{INDENT}{sid}{role}  "{preview}"')


def _print_tools_section(tools: dict[str, Any]) -> None:
    print(f"Tools ({len(tools)}):")
    for name in sorted(tools.keys()):
        t = tools[name]
        preview = _truncate(t.description, 80)
        print(f'{INDENT}{name}  "{preview}"')


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
