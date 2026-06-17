"""`clops lint <pkg>` — run the importable linter against an Op library.

Exits:
    0 — no findings, or warnings only.
    1 — at least one error-level finding, or the library failed to import.
    2 — argparse usage error (handled upstream).
"""

from __future__ import annotations

import sys
from typing import Any

from clops.linter import Severity, check_library
from clops.registry import registry


def add_arguments(parser) -> None:
    parser.add_argument(
        "library",
        help="Python import path of the Op library to lint (e.g. my_company.ops).",
    )


def run(ns) -> int:
    try:
        result = check_library(ns.library)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[FATAL] Failed to import {ns.library!r}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    for finding in result.findings:
        stream = sys.stderr if finding.severity is Severity.ERROR else sys.stdout
        print(str(finding), file=stream)

    if not result.findings:
        print(f"[OK] {_op_count_summary()}. No lint findings.")
        return 0

    total = len(result.findings)
    errs = len(result.errors)
    warns = len(result.warnings)
    print()
    print(
        f"{total} finding{_s(total)}: "
        f"{errs} error{_s(errs)}, {warns} warning{_s(warns)}"
    )
    return 1 if errs else 0


def _s(n: int) -> str:
    return "" if n == 1 else "s"


def _op_count_summary() -> str:
    ops = registry.ops()
    n = len(ops)
    if n == 0:
        return "0 Ops registered"
    names = ", ".join(sorted(ops.keys()))
    return f"{n} Op{_s(n)} registered ({names})"
