"""clops — subcommand dispatcher.

Each subcommand lives in its own module under `clops.cli.<name>`
and exposes two functions:

    add_arguments(subparser) -> None    # register its flags
    run(ns) -> int                      # handle parsed args, return exit code

This keeps the dispatcher tiny and makes adding new commands a matter of
writing one module and one line in `_SUBCOMMANDS` below.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from clops.cli import init, lint, new_library, show


# Ordered so that --help prints them in this sequence.
_SUBCOMMANDS = (
    ("init", init, "Set up a project for the clops runtime."),
    ("new-library", new_library, "Scaffold a new Op library package."),
    ("lint", lint, "Lint an Op library."),
    ("show", show, "Print an Op library's shape (Ops, snippets, tools)."),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clops")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    for name, module, help_text in _SUBCOMMANDS:
        sp = sub.add_parser(name, help=help_text)
        module.add_arguments(sp)
        sp.set_defaults(handler=module.run)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(sys.argv[1:] if argv is None else argv)
    return ns.handler(ns)


if __name__ == "__main__":
    raise SystemExit(main())
