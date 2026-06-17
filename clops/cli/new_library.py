"""`clops new-library <dotted.path>` — scaffold an Op library package.

Generates an installable Python package on disk with:
    - pyproject.toml (installable via `pip install -e .`)
    - README.md with a short explainer
    - The Python namespace hierarchy for the dotted path
    - One demonstration Concept + one demonstration entry-tagged Op

Design notes:
    - Templates are inlined as Python string interpolations — no Jinja,
      no separate templates/ directory. Keeps the scaffold reviewable
      in one file.
    - Non-interactive. No prompts. Suitable for scripting.
    - Demo Op matches smoke-tests/01-hello-echo/ deliberately so it's
      familiar to anyone who's used the smoke tests.
"""

from __future__ import annotations

import keyword
import sys
from pathlib import Path
from typing import Any


# ---------- Validation ------------------------------------------------


def _validate_dotted_path(path: str) -> list[str]:
    if not path or not path.strip():
        raise ValueError("library name is required.")
    if path.startswith(".") or path.endswith(".") or ".." in path:
        raise ValueError(
            f"invalid dotted path {path!r}: stray dots."
        )
    segments = path.split(".")
    for seg in segments:
        if not seg:
            raise ValueError(
                f"invalid dotted path {path!r}: empty segment."
            )
        if not seg.isidentifier():
            raise ValueError(
                f"invalid segment {seg!r}: must be a valid Python identifier."
            )
        if keyword.iskeyword(seg):
            raise ValueError(
                f"invalid segment {seg!r}: Python keyword."
            )
    return segments


# ---------- Templates -------------------------------------------------


def _dotted_to_dist_name(dotted_path: str) -> str:
    """Convert a dotted import path to a PEP 508 distribution name.

    Replaces dots and underscores with hyphens so that
    ``my_company.support_ops`` becomes ``my-company-support-ops``.
    """
    return dotted_path.replace(".", "-").replace("_", "-")


def _render_pyproject(dotted_path: str, root_segment: str) -> str:
    dist_name = _dotted_to_dist_name(dotted_path)
    return f"""\
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{dist_name}"
version = "0.0.1"
description = "A clops Op library."
requires-python = ">=3.11"
dependencies = ["clops"]

[tool.setuptools.packages.find]
where = ["."]
include = ["{root_segment}*"]
"""


def _render_readme(dotted_path: str) -> str:
    return f"""\
# {dotted_path}

A clops Op library scaffolded by `clops new-library`.

## Install

```bash
pip install -e .
```

## Use

Add the library to your project's `.clops` file:

```
{dotted_path}
```

Or run:

```bash
clops init --library {dotted_path}
```

Then invoke the process from a Claude Code session:

> Run the Echo process with input "hello world".

## Structure

- `{dotted_path.replace('.', '/')}/concepts.py` — Concept declarations.
- `{dotted_path.replace('.', '/')}/ops.py` — Op declarations.
- `{dotted_path.replace('.', '/')}/__init__.py` — imports concepts + ops so registration runs on package import.

The scaffolded demo Op (`Echo`) is just a starting point. Delete it or replace it with your real Ops.

See `authoring-spec.md` in the clops repo for the full authoring reference.
"""


def _render_package_init_leaf(dotted_path: str) -> str:
    return f'''\
"""{dotted_path} — clops Op library."""

from {dotted_path} import concepts, ops  # noqa: F401  (registers via metaclass)

# If you add a snippets.py, this import ensures snippets auto-register too.
try:
    from {dotted_path} import snippets  # noqa: F401
except ImportError:
    pass
'''


def _render_package_init_namespace() -> str:
    return '"""Namespace package."""\n'


def _render_concepts_py() -> str:
    return '''\
"""Concepts — named, described handles for the things flowing between Ops."""

from clops import Concept


class Greeting(Concept):
    description = "A short greeting from the user."
'''


def _render_ops_py(dotted_path: str) -> str:
    return f'''\
"""Ops — the units of computation."""

from clops import Op
from {dotted_path}.concepts import Greeting


class Echo(Op):
    Input = Greeting
    Output = Greeting
    Intent = (
        "Echo the greeting back, prefixed with 'echo: '. "
        "This is the demo Op scaffolded by `clops new-library`. "
        "Delete it once you start writing your real Ops."
    )
    Meta = (
        "Minimal demo Op to verify the library installs and runs. "
        "Replace with your real Ops."
    )
    entry = True
'''


# ---------- File tree planning --------------------------------------


def _plan_files(root_dir: Path, segments: list[str], dotted_path: str) -> dict[Path, str]:
    """Return {absolute_path: content} for every file to write."""
    files: dict[Path, str] = {}
    root_segment = segments[0]

    files[root_dir / "pyproject.toml"] = _render_pyproject(dotted_path, root_segment)
    files[root_dir / "README.md"] = _render_readme(dotted_path)

    # Build out the nested package dirs.
    current = root_dir
    for i, seg in enumerate(segments):
        current = current / seg
        init_path = current / "__init__.py"
        if i == len(segments) - 1:
            # Leaf: the actual library package. Populate with concepts + ops.
            files[init_path] = _render_package_init_leaf(dotted_path)
            files[current / "concepts.py"] = _render_concepts_py()
            files[current / "ops.py"] = _render_ops_py(dotted_path)
        else:
            files[init_path] = _render_package_init_namespace()

    return files


# ---------- CLI surface ----------------------------------------------


def add_arguments(parser) -> None:
    parser.add_argument(
        "dotted_path",
        help="Dotted Python import path for the new library (e.g. my_company.support_ops).",
    )
    parser.add_argument(
        "--target",
        default=".",
        help="Parent directory to scaffold into (default: current working directory).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the root directory if it already exists.",
    )


def run(ns: Any) -> int:
    try:
        segments = _validate_dotted_path(ns.dotted_path)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    target = Path(ns.target).resolve()
    if not target.exists():
        print(
            f"[ERROR] target directory {target} does not exist.",
            file=sys.stderr,
        )
        return 1
    if not target.is_dir():
        print(
            f"[ERROR] target {target} is not a directory.",
            file=sys.stderr,
        )
        return 1

    root_dir = target / segments[0]
    if root_dir.exists() and not ns.force:
        print(
            f"[ERROR] {root_dir} already exists. Pass --force to overwrite, "
            "or pick a different library name.",
            file=sys.stderr,
        )
        return 1

    files = _plan_files(root_dir, segments, ns.dotted_path)

    for path, content in sorted(files.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"wrote {path.relative_to(target)}")

    print()
    print(f"Created {ns.dotted_path}. Next:")
    print(f"  pip install -e {root_dir.relative_to(target)}")
    print(f"  # Then, in a Claude Code project:")
    print(f"  clops init --library {ns.dotted_path}")
    return 0
