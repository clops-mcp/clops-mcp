#!/usr/bin/env python3
"""The one place that knows where the version lives.

The version is written in six places across four formats. Nothing kept them in
step, so every release involved hand-editing all six and hoping — and the first
`v0.4` release failed precisely because one of them was missed.

This module is the single list. Three things read it, which is the point:

    python scripts/set_version.py 0.4.2     # rewrite every location
    python scripts/set_version.py --check   # non-zero if they disagree
    tests/test_packaging.py                 # imports LOCATIONS directly

Adding a seventh location means editing this file and nothing else.

Not included, deliberately: the tagging example in the release workflow's
header comment. A workflow that rewrites itself mid-run is a bad idea, so that
example is version-agnostic instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class Location:
    """One place the version is written."""

    def __init__(self, path: str, description: str):
        self.path = path
        self.description = description

    @property
    def full(self) -> Path:
        return REPO_ROOT / self.path

    def read(self) -> str | None:
        raise NotImplementedError

    def write(self, version: str) -> None:
        raise NotImplementedError


class JsonLocation(Location):
    """A key path inside a JSON file.

    Rewritten by round-trip rather than by regex because
    `.claude-plugin/marketplace.json` holds two `"version"` keys — the
    marketplace schema's own `1.0.0` and the plugin's — and a regex over the
    file text hits the wrong one first. Verified that `json.dumps(...,
    indent=2)` reproduces all three files byte-for-byte, so the round-trip
    changes only the value it is asked to change.
    """

    def __init__(self, path: str, pointer: tuple, description: str):
        super().__init__(path, description)
        self.pointer = pointer

    def _resolve(self, doc):
        node = doc
        for key in self.pointer[:-1]:
            node = node[key]
        return node, self.pointer[-1]

    def read(self) -> str | None:
        if not self.full.exists():
            return None
        parent, key = self._resolve(json.loads(self.full.read_text()))
        return parent[key]

    def write(self, version: str) -> None:
        doc = json.loads(self.full.read_text())
        parent, key = self._resolve(doc)
        parent[key] = version
        self.full.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


class TextLocation(Location):
    """A regex with three groups: prefix, version, suffix.

    The pattern must match exactly once. A pattern that stops matching — because
    someone reworded the line around it — fails loudly here rather than silently
    leaving a stale version behind, which is the failure this whole module
    exists to prevent.
    """

    def __init__(self, path: str, pattern: str, description: str):
        super().__init__(path, description)
        self.pattern = re.compile(pattern, re.M)

    def read(self) -> str | None:
        if not self.full.exists():
            return None
        matches = self.pattern.findall(self.full.read_text())
        if len(matches) != 1:
            raise ValueError(
                f"{self.path}: pattern matched {len(matches)} times, expected 1. "
                "The surrounding text probably changed; update the pattern in "
                "scripts/set_version.py."
            )
        return matches[0][1]

    def write(self, version: str) -> None:
        text = self.full.read_text()
        self.read()  # revalidates the single-match invariant before writing
        self.full.write_text(self.pattern.sub(rf"\g<1>{version}\g<3>", text))


LOCATIONS: list[Location] = [
    TextLocation(
        "pyproject.toml",
        r'^(version = ")([^"]+)(")$',
        "the distribution version — what PyPI serves",
    ),
    JsonLocation(
        "server.json",
        ("version",),
        "the MCP registry entry",
    ),
    JsonLocation(
        ".claude-plugin/plugin.json",
        ("version",),
        "the Claude Code plugin manifest",
    ),
    JsonLocation(
        ".claude-plugin/marketplace.json",
        ("plugins", 0, "version"),
        "the plugin's entry in the marketplace listing",
    ),
    TextLocation(
        "README.md",
        r"^(Version )([^,]+)(, alpha)",
        "the maturity note readers see first",
    ),
    TextLocation(
        "clops/cli/init.py",
        r"(``clops-mcp==)([^`]+)(``)",
        "the pinned-release example in install_spec()'s docstring",
    ),
    TextLocation(
        "clops/cli/init.py",
        r"(clops-mcp@v)([^`]+)(``)",
        "the git-ref example in install_spec()'s docstring",
    ),
]


def read_all() -> dict[str, str | None]:
    """Every location's current version, keyed by a human-readable label."""
    return {f"{loc.path} ({loc.description})": loc.read() for loc in LOCATIONS}


def write_all(version: str) -> list[str]:
    """Set every location to `version`. Returns the paths that changed."""
    changed = []
    for loc in LOCATIONS:
        if not loc.full.exists():
            continue
        if loc.read() != version:
            loc.write(version)
            changed.append(loc.path)
    return sorted(set(changed))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set or check the version in every place it is written."
    )
    parser.add_argument("version", nargs="?", help="the version to write, e.g. 0.4.2")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report disagreement between locations and exit non-zero",
    )
    args = parser.parse_args()

    if args.check:
        current = read_all()
        present = {k: v for k, v in current.items() if v is not None}
        distinct = set(present.values())
        for label, value in present.items():
            print(f"  {value:<12} {label}")
        if len(distinct) > 1:
            print(f"\nDISAGREEMENT: {sorted(distinct)}", file=sys.stderr)
            return 1
        print(f"\nall locations agree: {distinct.pop() if distinct else '(none found)'}")
        return 0

    if not args.version:
        parser.error("give a version, or pass --check")

    changed = write_all(args.version.removeprefix("v"))
    if not changed:
        print(f"already at {args.version} — nothing to do")
    for path in changed:
        print(f"  updated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
